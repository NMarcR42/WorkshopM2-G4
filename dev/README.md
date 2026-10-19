# dev

Services métier et moteur de reprise : `api`, `auth`, `canary`, `remediation`, `frontend`. Rôle de chacun : [Services](../doc/ARCHITECTURE.md#services). Avancement : [roadmap](../doc/ROADMAP.md).

## Conventions des services Python

`api` est l'implémentation de référence ([`api/README.md`](api/README.md)).

- FastAPI, un `Dockerfile` (utilisateur non-root, healthcheck), une dépendance par ligne dans `requirements.txt` avec versions fixées.
- `GET /health` (le process répond), `GET /metrics` (Prometheus) ; `/ready` si le service dépend d'une base.
- Logs JSON sur stdout (`ts`, `level`, `service`, `msg` + champs utiles) : Promtail les collecte.
- Secrets lus depuis `NOM_FILE` (voir `api/app/config.py`), jamais depuis le code.
- Dépendance indisponible : `503` + `Retry-After`, pas de stack trace ; le service redémarre sans sa dépendance et s'y reconnecte.
- Lint `ruff` (`api/ruff.toml`), tests `pytest` ; la CI les lance.

## auth

Émet les JWT lus par `api` (`POST /login` → `{access_token, expires_in, username, role}`). Pas de base d'utilisateurs : comptes de démo dans `auth/app/users.json` (hash PBKDF2, `tools/hash_password.py` pour en créer). Mots de passe **fictifs**, en clair ici : `alice / alice-demo`, `bob / bob-demo` (clients), `ops / ops-demo` (operator). Le compte `canary` n'existe que si `CANARY_PASSWORD_FILE` est fourni (secret réel, à câbler avec la sonde). Les échecs de login sont journalisés (`event: login_failed`) pour le SIEM.

## frontend

Application React + Tailwind (Vite) **sobre** : login → comptes → paiement → résultat. Le gros effort visuel ira au dashboard de supervision.

- Appelle `/api/…` et `/auth/…` sur la même origine, donc **toujours via le WAF** ([routage](../doc/ARCHITECTURE.md#routage-de-lentrée-waf)) ; préfixes réglables à la construction par `VITE_API_BASE` / `VITE_AUTH_BASE`.
- Délai de 8 s par requête, échec affiché clairement, `Idempotency-Key` conservée tant que la réponse est incertaine : on peut réessayer sans payer deux fois.
- Ne parle ni à `remediation`, ni au `detector`, ni à l'`assistant`.
- Pas de `/metrics` : l'observabilité métier est côté API.

## Tester le parcours de paiement

Procédure complète (tests, parcours à la main, simulation d'incident) : [`doc/AUTH-FRONTEND.md`](../doc/AUTH-FRONTEND.md#comment-tester). `DEV_AUTH_URL` (défaut `http://localhost:8001`) règle la cible de `/auth` du serveur de dev.

## Contrats portés par DEV

- **JWT** émis par `auth`, lu par `api` : contrat dans [`api/README.md`](api/README.md#contrat-avec-auth).
- **`remediation`** : interfaces (a) et (b) dans [ARCHITECTURE](../doc/ARCHITECTURE.md). Deux executors (`local`, `ssh`) derrière la même interface, choisis par `REMEDIATION_MODE`.
- **`canary`** : `POST /verify` = transaction complète via le WAF + `GET /v1/ledger/check`.
