#!/usr/bin/env bash
# Enveloppe de docker compose : choisit les fichiers selon le role de la machine et le mode de remediation.
#   ROLES              all (defaut, mono-hote) | front back ops ai (un ou plusieurs, multi-machines)
#   REMEDIATION_MODE   local (defaut : docker-proxy) | ssh (Ansible/SSH, multi-machines)
# Usage : ./scripts/compose.sh up -d --build | down | logs -f api | ps
set -euo pipefail
cd "$(dirname "$0")/.."

. scripts/_env.sh
ROLES="${ROLES:-all}"
REMEDIATION_MODE="${REMEDIATION_MODE:-local}"
[ "$ROLES" = "all" ] && ROLES="front back ops ai"
case "$REMEDIATION_MODE" in local|ssh) ;; *) echo "REMEDIATION_MODE inconnu : $REMEDIATION_MODE (local|ssh)"; exit 1;; esac

files=(-f infra/compose/agents.yml)
for r in $ROLES; do
  [ -f "infra/compose/$r.yml" ] || { echo "Role inconnu : $r (front|back|ops|ai|all)"; exit 1; }
  files+=(-f "infra/compose/$r.yml")
  # La remediation ne vit que sur la machine ops : son mode d'execution s'y ajoute.
  [ "$r" = "ops" ] && files+=(-f "infra/compose/remediation-$REMEDIATION_MODE.yml")
done

exec docker compose --project-directory . "${files[@]}" "$@"
