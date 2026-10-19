#!/usr/bin/env bash
# Dechiffre cyber/secrets/secrets.enc.yaml vers .secrets/<nom> (un fichier par secret).
# Pour un deploiement PARTAGE (VM, demo). En dev local, preferer scripts/init-local.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

SRC=cyber/secrets/secrets.enc.yaml
[ -f "$SRC" ] || { echo "Manquant : $SRC (voir cyber/README.md)"; exit 1; }

. scripts/_env.sh
keys=(db_password jwt_secret engine_token grafana_admin_password)
[ "${REMEDIATION_MODE:-local}" = "ssh" ] && keys+=(ansible_ssh_key)   # cle SSH : mode ssh uniquement

umask 077
mkdir -p .secrets
for key in "${keys[@]}"; do
  sops -d --extract "[\"$key\"]" "$SRC" | tr -d '\n' > ".secrets/$key"
done
echo "Secrets ecrits dans .secrets/"
