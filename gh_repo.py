#!/usr/bin/env python3
"""
Standalone script to create or delete private GitHub repositories.
Uses only the Python standard library (no pip dependencies required).
"""

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

API_BASE_URL = "https://api.github.com"


def github_request(endpoint: str, token: str, method: str = "GET", data: dict = None) -> tuple[int, dict | str]:
    """Execute an HTTP request against the GitHub API using urllib."""
    url = f"{API_BASE_URL}{endpoint}" if endpoint.startswith("/") else endpoint
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Python-GitHub-Manager",
    }

    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as response:
            status = response.status
            content = response.read().decode("utf-8")
            if content:
                try:
                    return status, json.loads(content)
                except json.JSONDecodeError:
                    return status, content
            return status, {}
    except urllib.error.HTTPError as err:
        error_body = err.read().decode("utf-8", errors="replace")
        try:
            error_json = json.loads(error_body)
            message = error_json.get("message", error_body)
        except json.JSONDecodeError:
            message = error_body
        return err.code, f"Error {err.code}: {message}"
    except urllib.error.URLError as err:
        return 0, f"Connection error: {err.reason}"


def get_token(cli_token: str | None) -> str:
    """Retrieve the GitHub token via CLI argument, environment variable, or user prompt."""
    if cli_token:
        return cli_token.strip()
    env_token = os.getenv("GITHUB_TOKEN")
    if env_token:
        return env_token.strip()
    token = getpass.getpass("GitHub Personal Access Token: ").strip()
    if not token:
        print("Error: No token provided.", file=sys.stderr)
        sys.exit(1)
    return token


def get_current_user(token: str) -> str:
    """Fetch the username of the authenticated user."""
    status, data = github_request("/user", token)
    if status != 200:
        print(f"Authentication failed: {data}", file=sys.stderr)
        sys.exit(1)
    return data["login"]


def get_current_repo_exclusion() -> tuple[str | None, str | None]:
    """Detect the owner and name of the git repository hosting this script to prevent self-deletion."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        res = subprocess.run(
            ["git", "-C", script_dir, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            url = res.stdout.strip()
            clean_url = url[:-4] if url.endswith(".git") else url
            clean_url = clean_url.rstrip("/")
            if "github.com" in clean_url:
                if ":" in clean_url and not clean_url.startswith("http"):
                    path_part = clean_url.split(":")[-1]
                else:
                    path_part = clean_url.split("github.com/")[-1]
                parts = path_part.strip("/").split("/")
                if len(parts) >= 2:
                    return parts[-2].lower(), parts[-1].lower()
                elif len(parts) == 1:
                    return None, parts[0].lower()
    except Exception:
        pass

    # Fallback to parent directory name
    folder_name = os.path.basename(script_dir).lower()
    return None, folder_name


def format_github_date(iso_str: str) -> str:
    """Format a GitHub ISO timestamp into a human-readable relative and UTC date."""
    if not iso_str:
        return "Unknown"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = now - dt
        seconds = int(diff.total_seconds())

        if seconds < 60:
            rel = "a few seconds ago"
        elif seconds < 3600:
            m = max(1, seconds // 60)
            rel = f"{m} min ago"
        elif seconds < 86400:
            h = max(1, seconds // 3600)
            rel = f"{h} hr(s) ago"
        elif seconds < 86400 * 30:
            d = max(1, seconds // 86400)
            rel = f"{d} day(s) ago"
        elif seconds < 86400 * 365:
            mo = max(1, seconds // (86400 * 30))
            rel = f"{mo} month(s) ago"
        else:
            y = max(1, seconds // (86400 * 365))
            rel = f"{y} year(s) ago"

        return f"{rel} ({dt.strftime('%Y-%m-%d at %H:%M UTC')})"
    except Exception:
        return iso_str


def create_repo(args: argparse.Namespace) -> None:
    token = get_token(args.token)
    payload = {
        "name": args.name,
        "private": True,  # Always private as requested
        "auto_init": args.auto_init,
    }
    if args.description:
        payload["description"] = args.description

    if args.org:
        endpoint = f"/orgs/{args.org}/repos"
        target_name = f"{args.org}/{args.name}"
    else:
        endpoint = "/user/repos"
        user = get_current_user(token)
        target_name = f"{user}/{args.name}"

    print(f"Creating private repository '{target_name}'...")
    status, res = github_request(endpoint, token, method="POST", data=payload)

    if status == 201:
        print(f"✅ Repository created successfully: {res.get('html_url')}")
        print(f"   SSH Clone  : {res.get('ssh_url')}")
        print(f"   HTTPS Clone: {res.get('clone_url')}")
    else:
        print(f"❌ Failed to create repository: {res}", file=sys.stderr)
        sys.exit(1)


def parse_git_remote_url(url: str) -> tuple[str, str, str]:
    """
    Parse a git remote URL into (host, owner, repo).
    Handles HTTPS, SSH (git@host:owner/repo), and SCP-like URLs.
    Example:
      'https://github.com/reglisse69/centreon-ansible.git' -> ('github.com', 'reglisse69', 'centreon-ansible')
      'git@github.com:reglisse69/centreon-ansible.git' -> ('github.com', 'reglisse69', 'centreon-ansible')
      'https://git.scsd.fr/stephane/archives.git' -> ('git.scsd.fr', 'stephane', 'archives')
    """
    u = url.strip()
    if u.endswith(".git"):
        u = u[:-4]
    u = u.rstrip("/")
    if "@" in u and ":" in u and "://" not in u:
        host_part, path_part = u.split(":", 1)
        host = host_part.split("@")[-1].lower()
        parts = path_part.strip("/").split("/")
        owner = parts[0] if len(parts) > 1 else ""
        repo = parts[-1] if parts else ""
        return host, owner, repo
    if "://" in u:
        _, rest = u.split("://", 1)
        slash_parts = rest.split("/")
        host_part = slash_parts[0]
        if "@" in host_part:
            host_part = host_part.split("@")[-1]
        if ":" in host_part:
            host_part = host_part.split(":")[0]
        host = host_part.lower()
        owner = slash_parts[1] if len(slash_parts) > 2 else ""
        repo = slash_parts[-1] if len(slash_parts) > 1 else ""
        return host, owner, repo
    return "", "", ""


def find_local_clones(src_root: str, host: str, repo_name: str, owner: str = "") -> list[str]:
    """Search src_root for git repositories cloned from the specified host and repo_name."""
    matches = []
    expanded_root = os.path.expanduser(src_root)
    if not os.path.isdir(expanded_root):
        return matches

    clean_host = (
        host.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0].lower()
    )
    clean_target = repo_name.lower().rstrip("/")
    if clean_target.endswith(".git"):
        clean_target = clean_target[:-4]

    for root, dirs, files in os.walk(expanded_root):
        if ".git" in dirs:
            dirs.remove(".git")
            config_path = os.path.join(root, ".git", "config")
            if os.path.isfile(config_path):
                try:
                    urls = []
                    with open(config_path, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            if "url =" in line:
                                urls.append(line.split("url =")[-1].strip())
                    for url in urls:
                        u_host, u_owner, u_repo = parse_git_remote_url(url)
                        if clean_host in u_host:
                            u_r = u_repo.lower()
                            matched = (u_r == clean_target)
                            if not matched:
                                if u_r == f"teamwork_{clean_target}" or clean_target == f"teamwork_{u_r}":
                                    matched = True
                            if matched:
                                if not owner or not u_owner or u_owner.lower() == owner.lower():
                                    matches.append(root)
                                    break
                except Exception:
                    pass
    return matches


def prompt_delete_local_clones(
    repo_name: str,
    host: str,
    owner: str = "",
    src_root: str = "~/src",
    silent_if_none: bool = False,
    indent: str = "",
) -> None:
    """
    Search ~/src for local clones matching host and repo_name (and optionally owner).
    If found, prompt the user to delete each local clone directory.
    """
    local_clones = find_local_clones(src_root, host, repo_name, owner)
    if not local_clones:
        if not silent_if_none:
            print(f"{indent}ℹ️  No local clone of '{repo_name}' found in {src_root}.")
        return

    current_script_path = os.path.realpath(__file__)
    current_script_dir = os.path.dirname(current_script_path)

    for loc in local_clones:
        real_loc = os.path.realpath(loc)
        # Safety check: do not delete the repository containing this script
        if current_script_path.startswith(real_loc + os.sep) or real_loc == current_script_dir:
            print(f"{indent}🛡️  Local clone at '{loc}' hosts this running script (protected from deletion).")
            continue

        del_loc = input(
            f"{indent}👉 Local clone found at '{loc}'. Do you want to delete this directory? (y/N): "
        ).strip().lower()

        if del_loc in ("y", "yes", "o", "oui"):
            try:
                shutil.rmtree(loc)
                print(f"{indent}✅ Deleted local clone directory '{loc}'.")
            except Exception as e:
                print(f"{indent}❌ Failed to delete directory '{loc}': {e}", file=sys.stderr)
        else:
            print(f"{indent}ℹ️  Kept local clone directory '{loc}'.")


def delete_repo(args: argparse.Namespace) -> None:
    token = get_token(args.token)

    owner = args.org
    if not owner:
        owner = get_current_user(token)

    target_name = f"{owner}/{args.name}"

    # Safety check: avoid accidentally deleting the repository hosting this script
    excl_owner, excl_repo = get_current_repo_exclusion()
    if excl_repo and args.name.lower() == excl_repo.lower():
        if not excl_owner or excl_owner == owner.lower():
            print(f"🛑 WARNING: '{target_name}' is the repository hosting this script!", file=sys.stderr)
            confirm_self = input("Do you REALLY want to delete the repository containing this script? (type 'DELETE'): ").strip()
            if confirm_self != "DELETE":
                print("Action canceled to protect the current repository.")
                return

    if not args.yes:
        confirm = input(f"⚠️  Are you sure you want to permanently delete '{target_name}'? (y/N): ").strip().lower()
        if confirm not in ("y", "yes", "o", "oui"):
            print("Action canceled.")
            return

    print(f"Deleting repository '{target_name}'...")
    status, res = github_request(f"/repos/{owner}/{args.name}", token, method="DELETE")

    if status == 204:
        print(f"✅ Repository '{target_name}' successfully deleted.")
        prompt_delete_local_clones(args.name, host="github.com", owner=owner, silent_if_none=False)
    else:
        print(f"❌ Failed to delete repository: {res}", file=sys.stderr)
        sys.exit(1)


def list_all_repos(token: str, owner: str, is_org: bool) -> list[dict]:
    """Retrieve all repositories belonging to the specified owner with metadata."""
    repos = []
    page = 1
    while True:
        if is_org:
            endpoint = f"/orgs/{owner}/repos?type=all&per_page=100&page={page}"
        else:
            endpoint = f"/user/repos?affiliation=owner&per_page=100&page={page}"

        status, data = github_request(endpoint, token)
        if status != 200:
            print(f"❌ Error while fetching repositories: {data}", file=sys.stderr)
            sys.exit(1)
        if not isinstance(data, list) or not data:
            break

        for r in data:
            if r.get("owner", {}).get("login", "").lower() == owner.lower():
                repos.append({
                    "name": r["name"],
                    "updated_at": r.get("updated_at", ""),
                    "private": r.get("private", True),
                    "description": r.get("description") or "",
                })

        if len(data) < 100:
            break
        page += 1
    return repos


def delete_all_repos(args: argparse.Namespace) -> None:
    token = get_token(args.token)

    is_org = bool(args.org)
    owner = args.org if is_org else get_current_user(token)

    print(f"Searching for repositories owned by '{owner}'...")
    all_repos = list_all_repos(token, owner, is_org)

    if not all_repos:
        print(f"No repositories found for '{owner}'.")
        return

    # Automatically exclude the repository containing this script
    excl_owner, excl_repo = get_current_repo_exclusion()
    repos = []
    excluded = []
    for r in all_repos:
        same_owner = (not excl_owner) or (excl_owner == owner.lower())
        if same_owner and excl_repo and (r["name"].lower() == excl_repo.lower()):
            excluded.append(r["name"])
        else:
            repos.append(r)

    if excluded:
        for ex in excluded:
            print(f"🛡️  Current repository excluded: '{owner}/{ex}' (hosts this script, protected from deletion).")

    if not repos:
        print(f"No other repositories to process for '{owner}'.")
        return

    print(f"\n{len(repos)} repository(ies) eligible for deletion.")
    print("Processing one by one with mandatory confirmation for each repository (no -y flag).\n")

    deleted_count = 0
    skipped_count = 0
    failed_count = 0

    for i, r in enumerate(repos, start=1):
        name = r["name"]
        target_name = f"{owner}/{name}"
        date_str = format_github_date(r["updated_at"])
        visibility = "🔒 Private" if r["private"] else "🌐 Public"

        print(f"[{i}/{len(repos)}] 📦 {target_name} ({visibility})")
        print(f"       Last updated : {date_str}")
        if r["description"]:
            print(f"       Description  : {r['description']}")

        while True:
            choice = input(
                f"       👉 Delete '{target_name}'? (y: yes / n: no / q: quit): "
            ).strip().lower()

            if choice in ("y", "yes", "o", "oui"):
                print(f"       Deleting '{target_name}'...")
                status, res = github_request(f"/repos/{owner}/{name}", token, method="DELETE")
                if status == 204:
                    print(f"       ✅ Repository '{target_name}' deleted.")
                    prompt_delete_local_clones(name, host="github.com", owner=owner, silent_if_none=True, indent="       ")
                    print()
                    deleted_count += 1
                else:
                    print(f"       ❌ Failed to delete repository: {res}\n", file=sys.stderr)
                    failed_count += 1
                break
            elif choice in ("n", "no", "non", ""):
                print(f"       ⏭️  Skipped: {target_name}\n")
                skipped_count += 1
                break
            elif choice in ("q", "quit", "quitter"):
                remaining = len(repos) - (i - 1)
                print("\nAbort requested.")
                print(
                    f"Summary: {deleted_count} deleted, {skipped_count} skipped, "
                    f"{failed_count} failed, {remaining} unprocessed."
                )
                return
            else:
                print("       Unrecognized input. Type 'y' (yes), 'n' (no/skip), or 'q' (quit).")

    print(
        f"Finished: {deleted_count} deleted, {skipped_count} skipped, {failed_count} failed."
    )


def update_remote_url(old_url: str, old_name: str, new_name: str) -> str:
    """
    Replace old repository name with new repository name in git remote URL,
    preserving protocol, host, owner, and .git suffix.
    """
    has_git = old_url.rstrip("/").endswith(".git")
    clean = old_url.rstrip("/")
    if has_git:
        clean = clean[:-4]
    if clean.lower().endswith(f"/{old_name.lower()}"):
        prefix = clean[:-len(old_name)]
        new_clean = f"{prefix}{new_name}"
        return f"{new_clean}.git" if has_git else new_clean
    return old_url


def rename_github_repo(args: argparse.Namespace) -> None:
    """
    Rename a GitHub repository on the remote server and update local clones in ~/src:
    1. Rename repository via GitHub API (PATCH /repos/{owner}/{old_name}).
    2. Search ~/src for local clones.
    3. For each clone:
       - Update git remote URLs to point to the new repository name.
       - Rename the local directory if its name matches old_name.
    """
    raw_old = args.old_name.strip()
    raw_new = args.new_name.strip()

    if not raw_old or not raw_new:
        print("Error: Both old_name and new_name are required.", file=sys.stderr)
        sys.exit(1)

    owner_from_input = None
    if "/" in raw_old:
        parts = raw_old.split("/", 1)
        owner_from_input = parts[0]
        old_name = parts[1]
    else:
        old_name = raw_old

    new_name = raw_new.split("/")[-1]

    if old_name == new_name:
        print(f"Error: Old name and new name are identical ('{old_name}').", file=sys.stderr)
        sys.exit(1)

    token = get_token(args.token)
    owner = args.org or owner_from_input or get_current_user(token)

    old_target = f"{owner}/{old_name}"
    new_target = f"{owner}/{new_name}"

    if not getattr(args, "yes", False):
        confirm = input(
            f"⚠️  Are you sure you want to rename GitHub repository '{old_target}' to '{new_target}'? (y/N): "
        ).strip().lower()
        if confirm not in ("y", "yes", "o", "oui"):
            print("Action canceled.")
            return

    print(f"Renaming remote GitHub repository '{old_target}' to '{new_target}'...")
    status, res = github_request(
        f"/repos/{owner}/{old_name}",
        token,
        method="PATCH",
        data={"name": new_name},
    )

    if status != 200:
        print(f"❌ Failed to rename GitHub repository: {res}", file=sys.stderr)
        sys.exit(1)

    new_html_url = res.get("html_url", f"https://github.com/{new_target}")
    print(f"✅ GitHub repository successfully renamed to '{new_target}'.")
    print(f"   URL: {new_html_url}")

    # Search for local clones in ~/src
    print(f"\n🔍 Searching for local clones of '{old_name}' in ~/src...")
    local_clones = find_local_clones("~/src", "github.com", old_name, owner)

    if not local_clones:
        print(f"ℹ️  No local clone of '{old_name}' found in ~/src.")
        return

    current_script_path = os.path.realpath(__file__)

    for loc in local_clones:
        print(f"\n📦 Found local clone at '{loc}':")
        real_loc = os.path.realpath(loc)
        parent_dir = os.path.dirname(loc)
        old_folder_name = os.path.basename(loc)
        target_folder = os.path.join(parent_dir, new_name)

        working_loc = loc

        # 1. Rename directory if its folder name matches old_name
        if old_folder_name.lower() == old_name.lower():
            if target_folder == loc:
                print(f"   ℹ️  Local directory name already matches '{new_name}'.")
            elif os.path.exists(target_folder):
                print(f"   ⚠️  Target directory '{target_folder}' already exists. Skipping directory rename.")
            else:
                try:
                    os.rename(loc, target_folder)
                    print(f"   📁 Renamed local directory:\n      '{loc}' -> '{target_folder}'")
                    working_loc = target_folder
                    # If this directory contains the active script, update process working directory
                    if current_script_path.startswith(real_loc + os.sep) or real_loc == os.path.dirname(current_script_path):
                        try:
                            os.chdir(working_loc)
                        except Exception:
                            pass
                except Exception as e:
                    print(f"   ❌ Failed to rename directory '{loc}': {e}", file=sys.stderr)
        else:
            print(f"   ℹ️  Directory name is '{old_folder_name}' (differs from '{old_name}'). Keeping folder name.")

        # 2. Update git remotes in the local repository
        try:
            rem_res = subprocess.run(
                ["git", "-C", working_loc, "remote"],
                capture_output=True,
                text=True,
                check=False,
            )
            remotes = [r.strip() for r in rem_res.stdout.splitlines() if r.strip()]
            for rem in remotes:
                url_res = subprocess.run(
                    ["git", "-C", working_loc, "remote", "get-url", rem],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if url_res.returncode == 0:
                    old_url = url_res.stdout.strip()
                    if "github.com" in old_url.lower() and f"/{old_name.lower()}" in old_url.lower():
                        new_url = update_remote_url(old_url, old_name, new_name)
                        if new_url != old_url:
                            set_res = subprocess.run(
                                ["git", "-C", working_loc, "remote", "set-url", rem, new_url],
                                check=False,
                            )
                            if set_res.returncode == 0:
                                print(f"   🔗 Updated remote '{rem}':\n      {old_url} -> {new_url}")
                            else:
                                print(f"   ❌ Failed to update remote '{rem}'.", file=sys.stderr)

            # Test connection to new remote
            fetch_res = subprocess.run(
                ["git", "-C", working_loc, "fetch", "--dry-run"],
                capture_output=True,
                text=True,
                check=False,
            )
            if fetch_res.returncode == 0:
                print("   📡 Remote connection verified successfully.")
            else:
                print(f"   ⚠️  Remote fetch notice: {fetch_res.stderr.strip() or 'OK'}")
        except Exception as e:
            print(f"   ❌ Error updating git remotes in '{working_loc}': {e}", file=sys.stderr)


def transform_gitea_name_to_github(name: str) -> str:
    """
    Transform Gitea repository name to GitHub repository name.
    - If the name starts with 'teamwork_', keep only the trailing part:
      e.g. teamwork_gerflor -> gerflor
    - If the name contains an underscore (e.g. python_centreon),
      reverse the parts separated by '-': e.g. centreon-python.
    - Otherwise, keep the original name.
    """
    if name.startswith("teamwork_"):
        return name[len("teamwork_"):]
    if "_" in name:
        parts = [p for p in name.split("_") if p]
        return "-".join(reversed(parts))
    return name


def trim_repository_history(repo_dir: str, months: int = 3, min_commits: int = 3) -> None:
    """
    Trim repository history to keep commits from the last `months` (default 3 months)
    and at least `min_commits` (default 3 commits).
    The oldest preserved commit becomes the new root of the branch.
    """
    now = int(time.time())
    cutoff = now - (months * 30 * 86400)

    branches_res = subprocess.run(
        ["git", "-C", repo_dir, "for-each-ref", "--format=%(refname)", "refs/heads"],
        capture_output=True,
        text=True,
        check=False,
    )
    if branches_res.returncode != 0 or not branches_res.stdout.strip():
        return

    branches = branches_res.stdout.strip().splitlines()
    grafted_count = 0

    for b in branches:
        log_res = subprocess.run(
            ["git", "-C", repo_dir, "log", b, "--format=%H %ct"],
            capture_output=True,
            text=True,
            check=False,
        )
        if log_res.returncode != 0 or not log_res.stdout.strip():
            continue

        commits = log_res.stdout.strip().splitlines()
        if len(commits) <= min_commits:
            continue

        kept = []
        for line in commits:
            parts = line.split()
            if len(parts) < 2:
                continue
            h, ct = parts[0], int(parts[1])
            if len(kept) < min_commits or ct >= cutoff:
                kept.append(h)
            else:
                break

        if len(kept) < len(commits):
            oldest_kept = kept[-1]
            graft_res = subprocess.run(
                ["git", "-C", repo_dir, "replace", "--graft", oldest_kept],
                check=False,
                capture_output=True,
            )
            if graft_res.returncode == 0:
                grafted_count += 1

    if grafted_count > 0:
        print(f"   ✂️  Trimmed history: keeping last {months} months (min {min_commits} commits).")


def clean_gitea_references(repo_dir: str, months: int = 3, min_commits: int = 3) -> None:
    """
    Clean up repository for GitHub migration / trimming:
    - Trim history to the last `months` (minimum `min_commits`).
    - Remove the .gitea directory across all branches using git-filter-repo.
    - Delete any Gitea-internal pull request references (refs/pull/*).
    """
    # 1. Clean Gitea pull request refs if any exist
    pr_refs = subprocess.run(
        ["git", "-C", repo_dir, "for-each-ref", "--format=%(refname)", "refs/pull"],
        capture_output=True,
        text=True,
        check=False,
    )
    if pr_refs.returncode == 0 and pr_refs.stdout.strip():
        deleted_refs = 0
        for ref in pr_refs.stdout.strip().splitlines():
            ref = ref.strip()
            if ref:
                del_res = subprocess.run(
                    ["git", "-C", repo_dir, "update-ref", "-d", ref],
                    check=False,
                    capture_output=True,
                )
                if del_res.returncode == 0:
                    deleted_refs += 1
        if deleted_refs > 0:
            print(f"   🧹 Removed {deleted_refs} Gitea internal PR reference(s) (refs/pull/*).")

    # 2. Trim commit history (months / min_commits)
    trim_repository_history(repo_dir, months=months, min_commits=min_commits)

    # 3. Remove .gitea directory and permanently bake new clean history
    print("   🧹 Removing '.gitea' directory & baking clean history...")
    res = subprocess.run(
        ["git", "-C", repo_dir, "filter-repo", "--path", ".gitea", "--invert-paths", "--force"],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode == 0:
        print("   ✅ Cleaned '.gitea' directory and baked trimmed history.")
    else:
        # Fallback to filter-branch if filter-repo is unavailable
        fb_res = subprocess.run(
            [
                "git", "-C", repo_dir, "filter-branch", "--force",
                "--tree-filter", "rm -rf .gitea",
                "--prune-empty", "--tag-name-filter", "cat", "--", "--all"
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if fb_res.returncode == 0:
            print("   ✅ Successfully cleaned '.gitea' directory via filter-branch.")
        else:
            print("   ℹ️  No '.gitea' directory found or already clean.")



def migrate_repo(args: argparse.Namespace) -> None:
    """
    Migrate a repository from Gitea (https://git.scsd.fr) to GitHub:
    1. Create an empty private GitHub repository.
    2. Clone the Gitea repo locally in mirror mode.
    3. Remove Gitea references (.gitea directory and internal refs).
    4. Push all branches, tags, and refs to GitHub.
    5. Clean up temporary mirror files.
    """
    gitea_input = args.source.strip()
    if (
        gitea_input.startswith("http://")
        or gitea_input.startswith("https://")
        or gitea_input.startswith("git@")
    ):
        gitea_url = gitea_input
        raw_name = gitea_input.rstrip("/").split("/")[-1]
        if raw_name.endswith(".git"):
            raw_name = raw_name[:-4]
    else:
        raw_name = gitea_input[:-4] if gitea_input.endswith(".git") else gitea_input
        gitea_url = f"{args.gitea_base_url.rstrip('/')}/{args.gitea_user}/{raw_name}.git"

    # Use explicit target if provided, otherwise transform Gitea name
    github_name = args.target.strip() if args.target else transform_gitea_name_to_github(raw_name)

    token = get_token(args.token)
    owner = args.org if args.org else get_current_user(token)
    target_full_name = f"{owner}/{github_name}"

    print(f"--- Starting Migration ---")
    print(f"Source Gitea repository : {gitea_url}")
    print(f"Target GitHub repository: {target_full_name}")

    # 1. Create empty private GitHub repository
    status, check_data = github_request(f"/repos/{owner}/{github_name}", token)
    if status == 200:
        print(f"⚠️  GitHub repository '{target_full_name}' already exists.")
        proceed = (
            input("Do you want to proceed and push to this existing repository? (y/N): ")
            .strip()
            .lower()
        )
        if proceed not in ("y", "yes", "o", "oui"):
            print("Migration aborted.")
            return
    elif status == 404:
        print(f"\n1/ Creating empty private GitHub repository '{target_full_name}'...")
        payload = {
            "name": github_name,
            "private": True,
            "auto_init": False,  # Must be empty for mirror push
        }
        if args.description:
            payload["description"] = args.description

        endpoint = f"/orgs/{args.org}/repos" if args.org else "/user/repos"
        create_status, res = github_request(endpoint, token, method="POST", data=payload)
        if create_status != 201:
            print(f"❌ Failed to create GitHub repository: {res}", file=sys.stderr)
            sys.exit(1)
        print(f"   ✅ Created: {res.get('html_url')}")
    else:
        print(f"❌ Error checking GitHub repository: {check_data}", file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="gh_migrate_") as tmpdir:
        # 2. Clone Gitea repo in mirror mode in a temporary directory
        clone_path = os.path.join(tmpdir, f"{raw_name}.git")
        print(f"\n2/ Cloning Gitea repository in mirror mode from: {gitea_url}...")
        clone_res = subprocess.run(
            ["git", "clone", "--mirror", gitea_url, clone_path],
            check=False,
        )
        if clone_res.returncode != 0:
            print(f"❌ Failed to clone mirror from {gitea_url}", file=sys.stderr)
            sys.exit(1)

        # 3. Clean Gitea references (including .gitea directory)
        print(f"\n3/ Cleaning Gitea references and '.gitea' directory...")
        clean_gitea_references(clone_path)

        # 4. Push mirror to GitHub
        print(f"\n4/ Pushing mirror to GitHub: {target_full_name}...")
        auth_push_url = f"https://x-access-token:{token}@github.com/{owner}/{github_name}.git"
        subprocess.run(
            ["git", "-C", clone_path, "remote", "add", "github-target", auth_push_url],
            check=True,
            capture_output=True,
        )
        push_res = subprocess.run(
            ["git", "-C", clone_path, "push", "--mirror", "github-target"],
            check=False,
        )
        if push_res.returncode != 0:
            print(f"❌ Failed to push mirror to GitHub ({target_full_name})", file=sys.stderr)
            sys.exit(1)

    # 5. Cleanup is handled automatically by TemporaryDirectory
    print(f"\n5/ Cleaned up temporary mirror files.")
    print(f"\n🎉 Successfully migrated '{raw_name}' (Gitea) -> '{target_full_name}' (GitHub)!")
    print(f"   GitHub repository URL: https://github.com/{owner}/{github_name}")

    # Propose deleting the source repository on Gitea
    confirm_del = input(
        f"\n👉 Do you want to delete the source Gitea repository '{raw_name}' now? (y/N): "
    ).strip().lower()

    if confirm_del in ("y", "yes", "o", "oui"):
        del_args = argparse.Namespace(
            name=raw_name,
            token=None,
            org=None,
            yes=True,
            gitea_url=args.gitea_base_url,
        )
        print()
        delete_gitea_repo(del_args)

        # Propose cloning the new GitHub repo into ~/src/twmk/<github_name>
        target_clone_dir = os.path.expanduser(f"~/src/twmk/{github_name}")
        clone_choice = input(
            f"\n👉 Do you want to clone the new GitHub repository into '{target_clone_dir}'? (y/N): "
        ).strip().lower()
        if clone_choice in ("y", "yes", "o", "oui"):
            if os.path.exists(target_clone_dir):
                backup_dir = f"{target_clone_dir}.gitea"
                if os.path.exists(backup_dir):
                    print(f"⚠️  Backup directory '{backup_dir}' already exists. Overwriting old backup...")
                    shutil.rmtree(backup_dir)
                os.rename(target_clone_dir, backup_dir)
                print(f"📦 Renamed existing '{target_clone_dir}' to '{backup_dir}'.")

            os.makedirs(os.path.dirname(target_clone_dir), exist_ok=True)
            print(f"Cloning {target_full_name} into '{target_clone_dir}'...")
            auth_clone_url = f"https://x-access-token:{token}@github.com/{owner}/{github_name}.git"
            res = subprocess.run(
                ["git", "clone", auth_clone_url, target_clone_dir],
                check=False,
            )
            if res.returncode == 0:
                clean_gh_url = f"https://github.com/{owner}/{github_name}.git"
                subprocess.run(
                    ["git", "-C", target_clone_dir, "remote", "set-url", "origin", clean_gh_url],
                    check=False,
                )
                print(f"✅ Repository successfully cloned into '{target_clone_dir}'.")
            else:
                print(f"❌ Failed to clone repository into '{target_clone_dir}'.", file=sys.stderr)
    else:
        print(f"ℹ️  To delete it later, run: ./gh_repo.py del-gitea {raw_name}")


def get_dir_size(path: str) -> str:
    """Return human-readable directory size using du or python fallback."""
    try:
        res = subprocess.run(["du", "-sh", path], capture_output=True, text=True, check=False)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip().split()[0]
    except Exception:
        pass
    try:
        total = sum(
            os.path.getsize(os.path.join(r, f))
            for r, _, files in os.walk(path)
            for f in files
            if os.path.exists(os.path.join(r, f))
        )
        for unit in ("B", "KB", "MB", "GB"):
            if total < 1024.0:
                return f"{total:.1f} {unit}" if unit != "B" else f"{total} B"
            total /= 1024.0
        return f"{total:.1f} TB"
    except Exception:
        return "unknown"


def trim_repo(args: argparse.Namespace) -> None:
    """
    Trim repository history on GitHub:
    - Keep commits from the last --months (default: 3) and at least --min-commits (default: 3).
    - Remove .gitea directory and clean Gitea-specific references if present.
    - Force-push trimmed history to GitHub.
    - Optionally reset/align local clone if present in ~/src/twmk/<repo>.
    """
    input_name = args.name.strip()
    parsed_owner = None

    if os.path.isdir(os.path.expanduser(input_name)):
        repo = os.path.basename(os.path.abspath(os.path.expanduser(input_name)))
    elif "/" in input_name and not input_name.startswith("http"):
        parts = input_name.split("/")
        parsed_owner = parts[0]
        repo = parts[1]
    else:
        repo = input_name.rstrip("/").split("/")[-1]
        if repo.endswith(".git"):
            repo = repo[:-4]

    token = get_token(args.token)
    owner = args.org if args.org else (parsed_owner or get_current_user(token))
    target_full_name = f"{owner}/{repo}"

    # Protect current repository hosting this script
    excl_owner, excl_repo = get_current_repo_exclusion()
    if excl_repo and repo.lower() == excl_repo.lower():
        if not excl_owner or excl_owner == owner.lower():
            print(
                f"🛑 WARNING: '{target_full_name}' is the repository hosting this script! Trimming it is prohibited.",
                file=sys.stderr,
            )
            sys.exit(1)

    # Check that repo exists on GitHub
    status, repo_data = github_request(f"/repos/{owner}/{repo}", token)
    if status != 200:
        print(f"❌ Repository '{target_full_name}' not found on GitHub: {repo_data}", file=sys.stderr)
        sys.exit(1)

    print(f"--- Trimming Repository History for '{target_full_name}' ---")
    print(f"Rule: Keep commits from the last {args.months} month(s) (minimum {args.min_commits} commits).")

    if not args.yes:
        confirm = input(
            f"⚠️  This will REWRITE the git history of '{target_full_name}' on GitHub (force-push). Continue? (y/N): "
        ).strip().lower()
        if confirm not in ("y", "yes", "o", "oui"):
            print("Action canceled.")
            return

    with tempfile.TemporaryDirectory(prefix="gh_trim_") as tmpdir:
        clone_path = os.path.join(tmpdir, f"{repo}.git")
        auth_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"

        print(f"\n1/ Cloning mirror from GitHub: {target_full_name}...")
        clone_res = subprocess.run(
            ["git", "clone", "--mirror", auth_url, clone_path],
            check=False,
        )
        if clone_res.returncode != 0:
            print(f"❌ Failed to clone mirror from GitHub ({target_full_name})", file=sys.stderr)
            sys.exit(1)

        mirror_size_before = get_dir_size(clone_path)

        print(f"\n2/ Trimming history and cleaning references...")
        clean_gitea_references(clone_path, months=args.months, min_commits=args.min_commits)
        mirror_size_after = get_dir_size(clone_path)
        print(f"   📊 Mirror repository size: {mirror_size_before} -> {mirror_size_after}")

        print(f"\n3/ Force-pushing trimmed mirror to GitHub ({target_full_name})...")
        push_res = subprocess.run(
            ["git", "-C", clone_path, "push", "--mirror", "--force", auth_url],
            check=False,
        )
        if push_res.returncode != 0:
            print(f"❌ Failed to force-push mirror to GitHub ({target_full_name})", file=sys.stderr)
            sys.exit(1)

    print(f"\n4/ Cleaned up temporary files.")
    print(f"\n🎉 Successfully trimmed repository '{target_full_name}' on GitHub!")
    print(f"   GitHub repository URL: https://github.com/{owner}/{repo}")

    # Check if a local clone exists in ~/src/twmk/<repo>
    local_dir = os.path.expanduser(f"~/src/twmk/{repo}")
    if os.path.isdir(local_dir):
        sync_choice = input(
            f"\n👉 Found local clone at '{local_dir}'. Reset it to match the newly trimmed history? (y/N): "
        ).strip().lower()
        if sync_choice in ("y", "yes", "o", "oui"):
            local_size_before = get_dir_size(local_dir)
            git_size_before = get_dir_size(os.path.join(local_dir, ".git"))

            subprocess.run(["git", "-C", local_dir, "fetch", "origin", "--prune"], check=False)
            branch_res = subprocess.run(
                ["git", "-C", local_dir, "symbolic-ref", "--short", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            )
            branch = branch_res.stdout.strip() or "main"
            subprocess.run(
                ["git", "-C", local_dir, "reset", "--hard", f"origin/{branch}"],
                check=False,
            )
            print("Purging local unreachable git objects and expiring reflog...")
            subprocess.run(
                ["git", "-C", local_dir, "reflog", "expire", "--expire=now", "--all"],
                check=False,
            )
            subprocess.run(
                ["git", "-C", local_dir, "gc", "--prune=now", "--aggressive"],
                check=False,
            )
            local_size_after = get_dir_size(local_dir)
            git_size_after = get_dir_size(os.path.join(local_dir, ".git"))

            print(f"✅ Local repository '{local_dir}' reset to origin/{branch}.")
            print(f"   📊 Local disk size : {local_size_before} -> {local_size_after} (Total)")
            print(f"   📊 Git objects size: {git_size_before} -> {git_size_after} (.git)")


def del_github_cmd(args: argparse.Namespace) -> None:
    """Handle del-github subcommand: single repo or all repos if --all is specified."""
    if getattr(args, "all", False):
        delete_all_repos(args)
    else:
        if not args.name:
            print("Error: Repository name is required (or use --all to review all repositories).", file=sys.stderr)
            sys.exit(1)
        delete_repo(args)


def gitea_request(
    endpoint: str,
    token: str,
    base_url: str = "https://git.scsd.fr",
    method: str = "GET",
    data: dict = None,
) -> tuple[int, dict | str]:
    """Execute an HTTP request against the Gitea API using urllib."""
    api_url = (
        f"{base_url.rstrip('/')}/api/v1{endpoint}"
        if not endpoint.startswith("http")
        else endpoint
    )
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Python-Gitea-Manager",
    }

    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(api_url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as response:
            status = response.status
            content = response.read().decode("utf-8")
            if content:
                try:
                    return status, json.loads(content)
                except json.JSONDecodeError:
                    return status, content
            return status, {}
    except urllib.error.HTTPError as err:
        error_body = err.read().decode("utf-8", errors="replace")
        try:
            error_json = json.loads(error_body)
            message = error_json.get("message", error_body)
        except json.JSONDecodeError:
            message = error_body
        return err.code, f"Error {err.code}: {message}"
    except urllib.error.URLError as err:
        return 0, f"Connection error: {err.reason}"


def get_gitea_token(cli_token: str | None) -> str:
    """Retrieve the Gitea token via CLI argument, environment variable, or user prompt."""
    if cli_token:
        return cli_token.strip()
    for var in ("GITEA_TOKEN", "GITEA_MAIN_TOKEN"):
        val = os.getenv(var)
        if val:
            return val.strip()
    token = getpass.getpass("Gitea Personal Access Token: ").strip()
    if not token:
        print("Error: No Gitea token provided.", file=sys.stderr)
        sys.exit(1)
    return token


def get_current_gitea_user(token: str, base_url: str) -> str:
    """Fetch the username of the authenticated Gitea user."""
    status, data = gitea_request("/user", token, base_url=base_url)
    if status != 200:
        print(f"Gitea authentication failed: {data}", file=sys.stderr)
        sys.exit(1)
    return data.get("username") or data.get("login")


def delete_gitea_repo(args: argparse.Namespace) -> None:
    """Delete a single repository from Gitea."""
    base_url = getattr(args, "gitea_url", None) or os.getenv("GITEA_URL", "https://git.scsd.fr")
    token = get_gitea_token(args.token)

    owner = args.org
    if not owner:
        owner = get_current_gitea_user(token, base_url)

    target_name = f"{owner}/{args.name}"

    if not getattr(args, "yes", False):
        confirm = input(
            f"⚠️  Are you sure you want to permanently delete Gitea repository '{target_name}'? (y/N): "
        ).strip().lower()
        if confirm not in ("y", "yes", "o", "oui"):
            print("Action canceled.")
            return

    print(f"Deleting Gitea repository '{target_name}'...")
    status, res = gitea_request(f"/repos/{owner}/{args.name}", token, base_url=base_url, method="DELETE")

    if status == 204:
        print(f"✅ Gitea repository '{target_name}' successfully deleted.")
        prompt_delete_local_clones(args.name, host=base_url, owner=owner, silent_if_none=False)
    else:
        print(f"❌ Failed to delete Gitea repository: {res}", file=sys.stderr)
        sys.exit(1)


def list_all_gitea_repos(token: str, owner: str, base_url: str, is_org: bool) -> list[dict]:
    """Retrieve all repositories belonging to the specified Gitea owner with metadata."""
    repos = []
    page = 1
    while True:
        if is_org:
            endpoint = f"/orgs/{owner}/repos?page={page}&limit=50"
        else:
            endpoint = f"/user/repos?page={page}&limit=50"

        status, data = gitea_request(endpoint, token, base_url=base_url)
        if status != 200:
            print(f"❌ Error while fetching Gitea repositories: {data}", file=sys.stderr)
            sys.exit(1)
        if not isinstance(data, list) or not data:
            break

        for r in data:
            owner_login = (
                r.get("owner", {}).get("login", "")
                or r.get("owner", {}).get("username", "")
            )
            if owner_login.lower() == owner.lower():
                repos.append({
                    "name": r["name"],
                    "updated_at": r.get("updated_at", ""),
                    "private": r.get("private", True),
                    "description": r.get("description") or "",
                })

        if len(data) < 50:
            break
        page += 1
    return repos


def delete_all_gitea_repos(args: argparse.Namespace) -> None:
    """Review and delete all repositories from Gitea one by one with interactive confirmation."""
    base_url = getattr(args, "gitea_url", None) or os.getenv("GITEA_URL", "https://git.scsd.fr")
    token = get_gitea_token(args.token)

    is_org = bool(args.org)
    owner = args.org if is_org else get_current_gitea_user(token, base_url)

    print(f"Searching for Gitea repositories owned by '{owner}' on {base_url}...")
    repos = list_all_gitea_repos(token, owner, base_url, is_org)

    if not repos:
        print(f"No repositories found for '{owner}' on Gitea.")
        return

    print(f"\n{len(repos)} repository(ies) found on Gitea for '{owner}'.")
    print("Processing one by one with mandatory confirmation for each repository (no -y flag).\n")

    deleted_count = 0
    skipped_count = 0
    failed_count = 0

    for i, r in enumerate(repos, start=1):
        name = r["name"]
        target_name = f"{owner}/{name}"
        date_str = format_github_date(r["updated_at"])
        visibility = "🔒 Private" if r["private"] else "🌐 Public"

        print(f"[{i}/{len(repos)}] 📦 {target_name} ({visibility})")
        print(f"       Last updated : {date_str}")
        if r["description"]:
            print(f"       Description  : {r['description']}")

        while True:
            choice = input(
                f"       👉 Delete Gitea repo '{target_name}'? (y: yes / n: no / q: quit): "
            ).strip().lower()

            if choice in ("y", "yes", "o", "oui"):
                print(f"       Deleting '{target_name}' from Gitea...")
                status, res = gitea_request(f"/repos/{owner}/{name}", token, base_url=base_url, method="DELETE")
                if status == 204:
                    print(f"       ✅ Gitea repository '{target_name}' deleted.")
                    prompt_delete_local_clones(name, host=base_url, owner=owner, silent_if_none=True, indent="       ")
                    print()
                    deleted_count += 1
                else:
                    print(f"       ❌ Failed to delete Gitea repository: {res}\n", file=sys.stderr)
                    failed_count += 1
                break
            elif choice in ("n", "no", "non", ""):
                print(f"       ⏭️  Skipped: {target_name}\n")
                skipped_count += 1
                break
            elif choice in ("q", "quit", "quitter"):
                remaining = len(repos) - (i - 1)
                print("\nAbort requested.")
                print(
                    f"Summary: {deleted_count} deleted, {skipped_count} skipped, "
                    f"{failed_count} failed, {remaining} unprocessed."
                )
                return
            else:
                print("       Unrecognized input. Type 'y' (yes), 'n' (no/skip), or 'q' (quit).")

    print(
        f"Finished: {deleted_count} deleted, {skipped_count} skipped, {failed_count} failed."
    )


def del_gitea_cmd(args: argparse.Namespace) -> None:
    """Handle del-gitea subcommand: single repo or all repos if --all is specified."""
    if getattr(args, "all", False):
        delete_all_gitea_repos(args)
    else:
        if not args.name:
            print("Error: Repository name is required (or use --all to review all repositories).", file=sys.stderr)
            sys.exit(1)
        delete_gitea_repo(args)


def list_local_repos(args: argparse.Namespace = None) -> None:
    """
    List all git repositories cloned in ~/src by inspecting .git/config:
    - One line per repository
    - Short name
    - Source (GitHub, Gitea, or other)
    - Date of last commit
    """
    src_dir = getattr(args, "path", None) or "~/src"
    expanded_root = os.path.expanduser(src_dir)

    if not os.path.isdir(expanded_root):
        print(f"Directory not found: {expanded_root}", file=sys.stderr)
        sys.exit(1)

    repos_info = []

    for root, dirs, files in os.walk(expanded_root):
        if ".git" in dirs:
            dirs.remove(".git")
            config_path = os.path.join(root, ".git", "config")
            if not os.path.isfile(config_path):
                continue

            # Read remote URL from config
            url = ""
            try:
                with open(config_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if "url =" in line:
                            url = line.split("url =")[-1].strip()
                            break
            except Exception:
                pass

            # Detect source
            u_low = url.lower()
            if "github.com" in u_low:
                source = "GitHub"
            elif "git.scsd.fr" in u_low or "gitea" in u_low:
                source = "Gitea"
            elif "gitlab" in u_low:
                source = "GitLab"
            elif url:
                source = "Other"
            else:
                source = "Local"

            # Get last commit date and relative time
            last_date_str = "No commits"
            try:
                res = subprocess.run(
                    ["git", "-C", root, "log", "-1", "--format=%ct"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if res.returncode == 0 and res.stdout.strip():
                    ct = int(res.stdout.strip())
                    now = int(time.time())
                    diff = now - ct
                    if diff < 60:
                        rel = "just now"
                    elif diff < 3600:
                        rel = f"{max(1, diff // 60)}m ago"
                    elif diff < 86400:
                        rel = f"{max(1, diff // 3600)}h ago"
                    elif diff < 86400 * 30:
                        rel = f"{max(1, diff // 86400)}d ago"
                    elif diff < 86400 * 365:
                        rel = f"{max(1, diff // (86400 * 30))}mo ago"
                    else:
                        rel = f"{max(1, diff // (86400 * 365))}y ago"

                    date_formatted = time.strftime("%Y-%m-%d %H:%M", time.localtime(ct))
                    last_date_str = f"{date_formatted} ({rel})"
            except Exception:
                pass

            short_name = os.path.basename(root)
            rel_path = os.path.relpath(root, expanded_root)
            repos_info.append({
                "name": short_name,
                "source": source,
                "date": last_date_str,
                "path": rel_path,
            })

    # Sort alphabetically by name then path
    repos_info.sort(key=lambda x: (x["name"].lower(), x["path"].lower()))

    # Calculate column widths for aligned layout
    max_name_len = max((len(r["name"]) for r in repos_info), default=15)
    max_name_len = max(max_name_len, len("REPOSITORY"))
    max_source_len = 8
    max_date_len = max((len(r["date"]) for r in repos_info), default=20)
    max_date_len = max(max_date_len, len("LAST COMMIT"))

    header = f"{'REPOSITORY':<{max_name_len}}  {'SOURCE':<{max_source_len}}  {'LAST COMMIT':<{max_date_len}}  PATH"
    print(header)
    print("-" * max(80, len(header) + 20))

    gitea_count = 0
    github_count = 0
    other_count = 0

    for r in repos_info:
        if r["source"] == "Gitea":
            gitea_count += 1
        elif r["source"] == "GitHub":
            github_count += 1
        else:
            other_count += 1

        print(f"{r['name']:<{max_name_len}}  {r['source']:<{max_source_len}}  {r['date']:<{max_date_len}}  {r['path']}")

    print("-" * max(80, len(header) + 20))
    print(f"Total: {len(repos_info)} repositories ({gitea_count} Gitea, {github_count} GitHub, {other_count} Other) in {src_dir}")


def main():
    parser = argparse.ArgumentParser(
        description="Repository manager for GitHub & Gitea (create, delete, rename, migrate, trim, list)"
    )
    parser.add_argument(
        "--token",
        "-t",
        help="API token (if not provided, read from env var or prompted interactively)",
    )
    parser.add_argument(
        "--org",
        "-o",
        help="Target organization (optional, default: personal user account)",
    )
    parser.add_argument(
        "--list-local",
        action="store_true",
        help="List all cloned git repositories in ~/src with name, source, and last commit date",
    )

    subparsers = parser.add_subparsers(dest="command", required=False)

    # Subcommand: create (GitHub)
    create_parser = subparsers.add_parser("create", help="Create a private repository on GitHub")
    create_parser.add_argument("name", help="Name of the repository to create")
    create_parser.add_argument("-d", "--description", help="Repository description (optional)")
    create_parser.add_argument(
        "--init",
        dest="auto_init",
        action="store_true",
        help="Initialize repository with a README.md",
    )
    create_parser.set_defaults(func=create_repo)

    # Subcommand: del-github
    del_gh_parser = subparsers.add_parser(
        "del-github",
        aliases=["delete"],
        help="Delete a repository on GitHub (or use -a / --all to review all)",
    )
    del_gh_parser.add_argument(
        "name",
        nargs="?",
        default=None,
        help="Name of the GitHub repository to delete (optional if --all is used)",
    )
    del_gh_parser.add_argument(
        "-a", "--all",
        action="store_true",
        help="Review and delete all GitHub repositories one by one",
    )
    del_gh_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Confirm deletion without prompting (single repo only)",
    )
    del_gh_parser.set_defaults(func=del_github_cmd)

    # Subcommand: del-github-all (direct alias for del-github --all)
    del_gh_all_parser = subparsers.add_parser(
        "del-github-all",
        aliases=["deleteall"],
        help="Review and delete all GitHub repositories one by one",
    )
    del_gh_all_parser.set_defaults(func=delete_all_repos)

    # Subcommand: ren-github
    ren_gh_parser = subparsers.add_parser(
        "ren-github",
        aliases=["rename", "rename-github"],
        help="Rename a repository on GitHub and update matching local clones in ~/src",
    )
    ren_gh_parser.add_argument("old_name", help="Current name of the GitHub repository")
    ren_gh_parser.add_argument("new_name", help="New name for the GitHub repository")
    ren_gh_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Confirm rename without interactive prompt",
    )
    ren_gh_parser.set_defaults(func=rename_github_repo)

    # Subcommand: del-gitea
    del_gt_parser = subparsers.add_parser(
        "del-gitea",
        help="Delete a repository on Gitea (or use -a / --all to review all)",
    )
    del_gt_parser.add_argument(
        "name",
        nargs="?",
        default=None,
        help="Name of the Gitea repository to delete (optional if --all is used)",
    )
    del_gt_parser.add_argument(
        "-a", "--all",
        action="store_true",
        help="Review and delete all Gitea repositories one by one",
    )
    del_gt_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Confirm deletion without prompting (single repo only)",
    )
    del_gt_parser.add_argument(
        "--gitea-url",
        default=os.getenv("GITEA_URL", "https://git.scsd.fr"),
        help="Gitea base URL (default: 'https://git.scsd.fr')",
    )
    del_gt_parser.set_defaults(func=del_gitea_cmd)

    # Subcommand: del-gitea-all (direct alias for del-gitea --all)
    del_gt_all_parser = subparsers.add_parser(
        "del-gitea-all",
        help="Review and delete all Gitea repositories one by one",
    )
    del_gt_all_parser.add_argument(
        "--gitea-url",
        default=os.getenv("GITEA_URL", "https://git.scsd.fr"),
        help="Gitea base URL (default: 'https://git.scsd.fr')",
    )
    del_gt_all_parser.set_defaults(func=delete_all_gitea_repos)

    # Subcommand: migrate
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Migrate a repository from Gitea (git.scsd.fr) to GitHub",
    )
    migrate_parser.add_argument(
        "source",
        help="Name of the Gitea repository (e.g. python_centreon) or full URL",
    )
    migrate_parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Target GitHub repository name (optional, defaults to inverted words e.g. centreon-python)",
    )
    migrate_parser.add_argument(
        "-d",
        "--description",
        help="Description for the new GitHub repository (optional)",
    )
    migrate_parser.add_argument(
        "--gitea-user",
        default="stephane",
        help="Gitea username/organization (default: 'stephane')",
    )
    migrate_parser.add_argument(
        "--gitea-base-url",
        default="https://git.scsd.fr",
        help="Gitea base URL (default: 'https://git.scsd.fr')",
    )
    migrate_parser.set_defaults(func=migrate_repo)

    # Subcommand: trim
    trim_parser = subparsers.add_parser(
        "trim",
        help="Trim commit history of an existing GitHub repository (keep 3 months / min 3 commits)",
    )
    trim_parser.add_argument(
        "name",
        help="Name of the GitHub repository (e.g. centreon-python) or local path",
    )
    trim_parser.add_argument(
        "-m", "--months",
        type=int,
        default=3,
        help="Number of months of history to keep (default: 3)",
    )
    trim_parser.add_argument(
        "-c", "--min-commits",
        type=int,
        default=3,
        help="Minimum number of commits to preserve (default: 3)",
    )
    trim_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Confirm history rewrite without interactive prompt",
    )
    trim_parser.set_defaults(func=trim_repo)

    # Subcommand: list-local
    list_local_parser = subparsers.add_parser(
        "list-local",
        help="List all cloned git repositories in ~/src with name, source, and last commit date",
    )
    list_local_parser.add_argument(
        "path",
        nargs="?",
        default="~/src",
        help="Root directory to search (default: ~/src)",
    )
    list_local_parser.set_defaults(func=list_local_repos)

    args = parser.parse_args()
    if getattr(args, "list_local", False):
        list_local_repos(args)
    elif hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
