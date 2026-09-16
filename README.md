# GitHub Setup & Tools

Scripts d'outillage Git/GitHub publics, sans aucun credential.

## Initialisation machine cliente (`init_github.sh`)

Configure Git pour travailler pendant 12 heures sans ressaisir vos identifiants, sans jamais les enregistrer sur le disque :

```bash
./init_github.sh
```

Ce script exécute :
- `git config --global user.name "Stephane Cassar"`
- `git config --global user.email "stephane.cassar@teamwork.net"`
- `git config --global init.defaultBranch main`
- `git config --global credential.helper 'cache --timeout=43200'`

> 💡 **Fonctionnement du cache 12h** : Lors du premier `git clone` ou `git push`, Git vous demandera votre Personal Access Token (PAT). Il sera conservé uniquement en mémoire RAM par le daemon Git pendant 43 200 secondes (12 heures), puis automatiquement purgé.

## Gestionnaire de dépôts (`gh_repo.py`)

Voir [gh_repo.md](gh_repo.md) pour la documentation complète de gestion des dépôts.
