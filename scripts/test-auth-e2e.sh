#!/usr/bin/env bash
# Test de bout en bout de l'authentification, avec (FACE_ENFORCE=true, IA simulee) et sans controle facial.
# Prerequis : Docker demarre, python, curl. Aucun code applicatif n'est modifie ; les services db/api/auth sont (re)demarres.
# Usage : ./scripts/test-auth-e2e.sh        (a relancer avant la demo)
#   FACE_TEST_HOST=<ip>  adresse de la machine hote vue depuis le conteneur auth (defaut host.docker.internal)
set -uo pipefail
cd "$(dirname "$0")/.."

API_PORT="${API_PORT:-$(grep -E '^API_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2)}"; API_PORT="${API_PORT:-8000}"
AUTH_PORT="${AUTH_PORT:-$(grep -E '^AUTH_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2)}"; AUTH_PORT="${AUTH_PORT:-8001}"
FAKE_PORT="${FAKE_PORT:-18600}"
FACE_TEST_HOST="${FACE_TEST_HOST:-host.docker.internal}"
# On teste que l'interpreteur tourne vraiment : sous Windows, python3 peut etre un raccourci du Store qui ne fait rien.
PY=""; for c in python3 python py; do "$c" -c "" >/dev/null 2>&1 && { PY="$c"; break; }; done
[ -n "$PY" ] || { echo "Aucun interpreteur Python fonctionnel."; exit 2; }
API="http://127.0.0.1:$API_PORT"; AUTH="http://127.0.0.1:$AUTH_PORT"
FAKE_PID=""; FAIL=0; RESULTS=()

compose() { ROLES=back ./scripts/compose.sh "$@"; }

check() { # check <n> <description> <attendu> <obtenu>
  if [ "$3" = "$4" ]; then RESULTS+=("PASS  $1. $2"); else RESULTS+=("FAIL  $1. $2 (attendu $3, obtenu $4)"); FAIL=1; fi
}
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$@" || true; }
login() { # login <user> <password> [token]
  local h=(); [ -n "${3:-}" ] && h=(-H "X-Face-Token: $3")
  code -X POST "$AUTH/auth/login" -H 'Content-Type: application/json' "${h[@]}" -d "{\"username\":\"$1\",\"password\":\"$2\"}"
}
wait_up() { for _ in $(seq 1 60); do [ "$(code "$1")" = 200 ] && return 0; sleep 2; done; return 1; }
cleanup() {
  [ -n "$FAKE_PID" ] && kill "$FAKE_PID" 2>/dev/null
  # Remet auth dans son etat normal (FACE_ENFORCE=false) pour ne pas laisser la demo en mode strict par erreur.
  FACE_ENFORCE=false FACE_SERVICE_URL= compose up -d auth >/dev/null 2>&1
}
trap cleanup EXIT

docker info >/dev/null 2>&1 || { echo "Docker ne repond pas : demarrer Docker Desktop puis relancer."; exit 2; }
./scripts/init-local.sh >/dev/null   # idempotent : cree .secrets/face_service_key s'il manque
CANARY_PW="$(cat .secrets/canary_password)"; PROBE="$(cat .secrets/synthetic_probe_token)"

echo "== Mode FACE_ENFORCE=false =="
FACE_ENFORCE=false FACE_SERVICE_URL= compose up -d --build db api auth || { echo "compose up a echoue"; exit 2; }
if wait_up "$API/health" && wait_up "$AUTH/health"; then RESULTS+=("PASS  1. db/api/auth demarrent et repondent sur /health"); else RESULTS+=("FAIL  1. services non joignables (api $API_PORT / auth $AUTH_PORT)"); FAIL=1; fi
check 2 "login alice sans X-Face-Token -> 200" 200 "$(login alice alice-demo)"
check 3 "transaction de controle /api/synthetic/transaction -> 200" 200 \
  "$(code -X POST "$API/api/synthetic/transaction" -H "Authorization: Bearer $PROBE" -H 'Content-Type: application/json' -d '{"amount":"1.00","currency":"EUR","label":"e2e"}')"
check 4 "login canary -> 200" 200 "$(login canary "$CANARY_PW")"

echo "== Mode FACE_ENFORCE=true (IA simulee sur le port $FAKE_PORT) =="
"$PY" scripts/fake_face_service.py "$FAKE_PORT" .secrets/face_service_key & FAKE_PID=$!
FACE_ENFORCE=true FACE_SERVICE_URL="http://$FACE_TEST_HOST:$FAKE_PORT" compose up -d auth >/dev/null || { echo "recreation de auth echouee"; exit 2; }
wait_up "$AUTH/health" || { RESULTS+=("FAIL  auth ne redemarre pas en mode true"); FAIL=1; }
check 5 "sans X-Face-Token -> 403" 403 "$(login alice alice-demo)"
check 6 "token invalide -> 403" 403 "$(login alice alice-demo mauvais-token)"
check 8 "token valide (simule) -> 200" 200 "$(login alice alice-demo tok-alice)"
check 8b "meme token rejoue (usage unique) -> 403" 403 "$(login alice alice-demo tok-alice)"
check 4b "canary exempte du visage en mode true -> 200" 200 "$(login canary "$CANARY_PW")"
kill "$FAKE_PID" 2>/dev/null; wait "$FAKE_PID" 2>/dev/null; FAKE_PID=""
check 7 "IA injoignable -> 503 propre" 503 "$(login alice alice-demo tok-alice)"
check 7b "auth toujours vivant apres la panne IA -> 200" 200 "$(code "$AUTH/health")"

echo; printf '%s\n' "${RESULTS[@]}"
[ "$FAIL" = 0 ] && echo "TOUT PASSE" || echo "ECHECS PRESENTS"
exit "$FAIL"
