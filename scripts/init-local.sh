#!/usr/bin/env bash
# Prepare un clone frais pour le MODE MONO-HOTE : aucune VM, aucune cle SSH, aucune cle age.
# Cree .env (si absent) et genere des secrets ALEATOIRES LOCAUX dans .secrets/ (ignore par git).
# Ces secrets ne servent qu'a ta machine. Pour un deploiement partage, utiliser SOPS : decrypt-secrets.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { cp .env.example .env; echo ".env cree"; }

umask 077
mkdir -p .secrets
for key in db_password jwt_secret engine_token grafana_admin_password canary_password synthetic_probe_token; do
  if [ ! -s ".secrets/$key" ]; then
    head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32 > ".secrets/$key"
    echo "secret genere : .secrets/$key"
  fi
done
echo "Pret. Lancer : ./scripts/compose.sh up -d --build"
