#!/usr/bin/env bash
set -e

# Configuration de l'identité Git
git config --global user.name "Stephane Cassar"
git config --global user.email "stephane.cassar@gmail.com"
git config --global init.defaultBranch main

# Cache les identifiants (PAT) en mémoire vive pendant 12h (43200 s)
# Rien n'est écrit sur le disque du client et les credentials expirent automatiquement
git config --global credential.helper 'cache --timeout=43200'

echo "✅ Configuration Git terminée :"
echo "  - user.name         : $(git config --global user.name)"
echo "  - user.email        : $(git config --global user.email)"
echo "  - init.defaultBranch: $(git config --global init.defaultBranch)"
echo "  - credential.helper : $(git config --global credential.helper)"
