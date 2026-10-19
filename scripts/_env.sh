#!/usr/bin/env bash
# Utilitaire (source par les autres scripts) : lit ROLES et REMEDIATION_MODE dans .env,
# sans ecraser une valeur deja fournie dans l'environnement (ROLES=back ./scripts/compose.sh ...).
# Les autres variables de .env sont lues par docker compose lui-meme.
env_default() {
  local key="$1" value
  [ -n "${!key-}" ] && return 0
  [ -f .env ] || return 0
  value=$(grep -E "^${key}=" .env | tail -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*//; s/[[:space:]]*$//' || true)
  [ -n "$value" ] && export "$key=$value"
  return 0
}
env_default ROLES
env_default REMEDIATION_MODE
