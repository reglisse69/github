# gh_repo.py - Gestionnaire de dépôts GitHub & Gitea

Script Python autonome (standard library uniquement, aucune dépendance `pip`) permettant de créer, supprimer, renommer, auditer, migrer et alléger l'historique de dépôts **GitHub** et **Gitea**.

---

## 🔒 Audit de sécurité & Gestion des Secrets

> **Statut de l'audit : Aucun secret en clair dans le code source.**

- **Aucun jeton ni mot de passe codé en dur** : Tous les accès à l'API GitHub et Gitea reposent sur des jetons d'accès personnels (PAT) fournis de manière dynamique.
- **Modes de transmission du jeton** (par ordre de priorité) :
  1. Argument CLI explicite : `--token` / `-t`
  2. Variables d'environnement : `GITHUB_TOKEN` (pour GitHub), `GITEA_TOKEN` ou `GITEA_MAIN_TOKEN` (pour Gitea)
  3. Saisie interactive masquée à l'écran (`getpass.getpass()`)
- **Protection des clones locaux** : Lors des opérations de clonage / push via miroir temporaire, l'URL authentifiée `https://x-access-token:...` n'est utilisée qu'en mémoire. L'URL du remote `origin` final est immédiatement nettoyée pour retirer le jeton (`git remote set-url origin https://github.com/...`).
- **Protection anti-auto-destruction** : Le script détecte automatiquement le dépôt qui l'héberge (ainsi que son répertoire local) pour empêcher sa suppression accidentelle ou un `trim` destructeur.

---

## 📋 Prérequis

- **Python 3.10+** (utilise les type annotations modernes `tuple[int, dict | str]`, etc.)
- **Git** installé et disponible dans le `PATH`
- *(Recommandé)* `git-filter-repo` pour l'allègement d'historique (avec repli automatique sur `git filter-branch` si absent)

---

## 🚀 Configuration rapide

Définir vos variables d'environnement dans votre shell (`~/.bashrc` ou `~/.zshrc`) :

```bash
export GITHUB_TOKEN="ghp_votre_token_github"
export GITEA_TOKEN="votre_token_gitea"
# Optionnel (valeur par défaut : https://git.scsd.fr)
export GITEA_URL="https://git.scsd.fr"
```

Rendre les scripts exécutables et lancer l'initialisation :

```bash
chmod +x gh_repo.py init_github.sh
./init_github.sh
```

Le script `init_github.sh` configure automatiquement votre identité Git globale (`user.name`, `user.email`), la branche par défaut (`main`), le `credential.helper`, et vérifie la connectivité à l'API GitHub sans stocker de secret en dur.

---

## 🛠️ Commandes et Fonctionnalités

### 1. Créer un dépôt GitHub privé (`create`)

Crée un nouveau dépôt privé sur votre compte personnel ou au sein d'une organisation.

```bash
# Sur votre compte personnel
./gh_repo.py create mon-projet -d "Description de mon projet"

# Avec initialisation d'un README.md
./gh_repo.py create mon-projet --init

# Dans une organisation GitHub
./gh_repo.py create mon-projet -o mon-organisation
```

---

### 2. Supprimer un dépôt GitHub (`del-github` / `delete`)

Supprime un dépôt distant. Propose également de rechercher et supprimer les clones locaux existants dans `~/src`.

```bash
# Suppression interactive avec confirmation
./gh_repo.py del-github mon-ancien-projet

# Suppression directe sans confirmation (-y)
./gh_repo.py del-github mon-ancien-projet -y

# Supprimer un dépôt appartenant à une organisation
./gh_repo.py del-github mon-ancien-projet -o mon-organisation
```

---

### 3. Revue & suppression interactive de tous les dépôts GitHub (`del-github-all` / `deleteall`)

Passe en revue l'ensemble de vos dépôts distants un par un avec affichage de la visibilité, de la date de dernière mise à jour et de la description, en demandant confirmation (`y`/`n`/`q`).

```bash
# Sur votre compte personnel
./gh_repo.py del-github-all

# Sur une organisation
./gh_repo.py del-github --all -o mon-organisation
```

> 🛡️ Le dépôt hébergeant le script est automatiquement détecté et exclu du traitement.

---

### 4. Renommer un dépôt GitHub (`ren-github` / `rename`)

Renomme le dépôt sur GitHub via l'API, recherche automatiquement tous les clones locaux dans `~/src`, renomme leur dossier local et met à jour leurs remotes Git (`origin`).

```bash
./gh_repo.py ren-github ancien-nom nouveau-nom

# Sans invite de confirmation
./gh_repo.py ren-github ancien-nom nouveau-nom -y

# Pour une organisation
./gh_repo.py ren-github ancien-nom nouveau-nom -o mon-organisation
```

---

### 5. Migrer de Gitea vers GitHub (`migrate`)

Migre un dépôt complet depuis Gitea (par défaut `https://git.scsd.fr`) vers GitHub :
1. Crée le dépôt privé cible sur GitHub.
2. Clone le dépôt Gitea en mode `--mirror` dans un dossier temporaire isolé.
3. Nettoie les références internes Gitea (`refs/pull/*`) et purge le dossier `.gitea`.
4. Raccourcit l'historique Git (par défaut conserve les 3 derniers mois / 3 commits minimum).
5. Pousse le miroir complet vers GitHub.
6. Propose de supprimer le dépôt source sur Gitea et de cloner le nouveau dépôt GitHub dans `~/src/twmk/<target>`.

```bash
# Migration simple (renommage automatique conventionnel e.g. python_centreon -> centreon-python)
./gh_repo.py migrate python_centreon

# En spécifiant un nom cible explicite
./gh_repo.py migrate python_centreon centreon-python -d "Client Centreon Python"

# Depuis une URL Gitea complète ou un utilisateur différent
./gh_repo.py migrate https://git.scsd.fr/stephane/mon-repo.git nouveau-repo
```

---

### 6. Alléger l'historique d'un dépôt GitHub (`trim`)

Permet de réduire la taille d'un dépôt GitHub en ne conservant que les commits récents et en purgeant les reliquats Gitea / fichiers orphelins :

```bash
# Conserver par défaut 3 mois et au moins 3 commits
./gh_repo.py trim mon-repo

# Personnaliser la période et le nombre minimum de commits
./gh_repo.py trim mon-repo --months 6 --min-commits 5 -y

# Si un clone local existe dans ~/src/twmk/mon-repo, propose de le réaligner et d'exécuter git gc
```

---

### 7. Gérer les dépôts Gitea (`del-gitea` & `del-gitea-all`)

Suppression unitaire ou revue globale interactive de vos dépôts hébergés sur Gitea.

```bash
# Supprimer un dépôt unitaire
./gh_repo.py del-gitea vieux-projet

# Revue et suppression interactive de tous les dépôts Gitea
./gh_repo.py del-gitea-all

# Spécifier une autre instance Gitea
./gh_repo.py del-gitea-all --gitea-url https://gitea.example.com
```

---

### 8. Lister les dépôts Git locaux (`list-local` ou `--list-local`)

Scanne récursivement un répertoire (par défaut `~/src`) pour afficher un tableau récapitulatif de tous les dépôts locaux avec leur provenance (GitHub, Gitea, GitLab, Local) et la date de leur dernier commit.

```bash
# Lister les dépôts dans ~/src
./gh_repo.py --list-local

# Lister les dépôts dans un autre dossier
./gh_repo.py list-local /chemin/vers/projets
```

Exemple de sortie :

```text
REPOSITORY       SOURCE    LAST COMMIT           PATH
----------------------------------------------------------------------------------------------------
centreon-ansible GitHub    2026-02-10 (1mo ago)  twmk/centreon-ansible
github           GitHub    2026-03-16 (just now) twmk/github
archives         Gitea     2025-11-20 (4mo ago)  archives
----------------------------------------------------------------------------------------------------
Total: 3 repositories (1 Gitea, 2 GitHub, 0 Other) in ~/src
```

---

## 🛡️ Mesures de protection intégrées

1. **Confirmation interactive stricte** : Les commandes de suppression de masse (`del-github-all`, `del-gitea-all`) requièrent une validation unitaire par dépôt sans option de contournement aveugle.
2. **Auto-préservation** : Impossible de supprimer ou de tronquer par mégarde le dépôt Git qui exécute le script.
3. **Sécurité des clones locaux** : Avant de supprimer un répertoire local, le script vérifie si le chemin d'exécution correspond au script en cours et bloque l'action si c'est le cas.
