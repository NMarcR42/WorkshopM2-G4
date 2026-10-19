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

Émet les JWT lus par `api` (`POST /login` → `{access_token, expires_in, username, role}`). Pas de base d'utilisateurs : comptes de démo dans `auth/app/users.json` (hash PBKDF2, `tools/hash_password.py` pour en créer). Mots de passe **fictifs**, en clair ici : `alice / alice-demo`, `bob / bob-demo` (clients), `ops / ops-demo` (operator). Le compte `canary` n'existe que si `CANARY_PASSWORD_FILE` est fourni (secret `canary_password`). Les échecs de login sont journalisés (`event: login_failed`) pour le SIEM.

## frontend

Application React + Tailwind (Vite) **sobre** : login → comptes → paiement → résultat. La vue du jury est un autre service : [`supervision`](#supervision).

- Appelle `/api/…` et `/auth/…` sur la même origine, donc **toujours via le WAF** ([routage](../doc/ARCHITECTURE.md#routage-de-lentrée-waf)) ; préfixes réglables à la construction par `VITE_API_BASE` / `VITE_AUTH_BASE`.
- Délai de 8 s par requête, échec affiché clairement, `Idempotency-Key` conservée tant que la réponse est incertaine : on peut réessayer sans payer deux fois.
- Ne parle ni à `remediation`, ni au `detector`, ni à l'`assistant`.
- Pas de `/metrics` : l'observabilité métier est côté API.

## canary

La sonde qui **prouve la reprise** : un conteneur qui redémarre ne prouve rien, un paiement qui passe si. Toutes les `CANARY_INTERVAL_S` (5 s) elle joue un client complet **via le WAF** (`WAF_URL`) : login → virement de 0.01 EUR entre `ACC-CANARY-A` et `ACC-CANARY-B` (avec `Idempotency-Key`) → `GET /v1/ledger/check`. Succès = tout est OK.

| Route | Rôle |
|---|---|
| `GET /metrics` | `payment_probe_success` (1 sain / 0 échec), `payment_probe_duration_seconds`, `payment_probe_last_run_timestamp_seconds`, `payment_probe_runs_total{result,step}` |
| `POST /verify` | Joue une passe maintenant. Toujours HTTP 200 : `{ok, failed_step, detail, duration_s, steps[]}` ; `ok: false` = le paiement ne passe pas |
| `GET /health` | Le process répond |

- Compte `canary` créé par `auth` grâce au secret `canary_password` (même fichier lu des deux côtés, jamais en clair dans git).
- Réseaux `edge` + `ctrl` + `obs`, aucun port publié ; ne parle ni au détecteur ni à l'assistant.
- Aucune relance en cas d'échec : une sonde qui réessaie masquerait les pannes intermittentes.
- Réglages : `CANARY_TIMEOUT_S`, `CANARY_FROM_ACCOUNT`, `CANARY_TO_ACCOUNT`, `CANARY_AMOUNT`, `CANARY_USERNAME`.

## remediation

Reçoit le signal (interface (a)), choisit l'action dans la liste fermée, l'exécute (interface (b)) et ne conclut qu'avec la preuve du canary.

Pour chaque signal (`POST /v1/anomalies`, Bearer `engine_token`, réponse 202) :
1. **Dédoublonnage** : même `anomaly_id`, incident déjà en cours ou résolu depuis moins de `REMEDIATION_COOLDOWN_S` (30 s) → on renvoie l'incident existant (`deduplicated: true`).
2. **Garde faux positif** : aucune IP à bloquer et le canary passe → `RESOLVED` sans rien toucher.
3. **Escalade** : `block_source` (si une IP suspecte a une part de trafic ≥ `BLOCK_MIN_SHARE`) → `restart_service` → `rollback_service`. Après chaque action, on attend que `POST /verify` passe (`VERIFY_TIMEOUT_S`, 30 s). Le premier succès clôt l'incident (`RESOLVED`, `resolved_by` = l'action) ; liste épuisée → `UNRESOLVED` (intervention humaine, visible).
4. **Journal** : `incident.json` (état + chronologie) et `<action>.json` par incident, dans le volume `incidents` ; relisible par `GET /v1/incidents` et `/v1/incidents/{id}` (même token). Un incident interrompu par un redémarrage du moteur est marqué `UNRESOLVED`.

Garde-fous : `target_service` limité à `api|auth|frontend` ; IP validées, jamais dans `PROTECTED_CIDRS` (réseaux Docker, donc le canary), 20 IP au plus ; blocage expiré après `BLOCK_TTL_S` (le moteur réécrit alors la liste) ; aucune valeur du signal n'atteint un shell. Métriques : `remediation_incidents_total{status}`, `remediation_actions_total{action,result}`, `remediation_recovery_seconds`, `remediation_incidents_active`.

Executor `local` : `POST /containers/<nom>/restart` via le docker-proxy (nom = `CONTAINER_NAME_TEMPLATE`, par défaut `resilience-{service}-1`) et écriture de `blocklist.txt` (voir [contrat WAF](../doc/ARCHITECTURE.md#interface-b--remediation--exécution-de-laction)). Executor `ssh` : `ansible-playbook` avec `-e` JSON, **non testé** (playbooks à écrire par INFRA).

## supervision

La vue du jury, une page : bandeau d'état (sain / dégradé / remédiation en cours / reprise vérifiée / inconnu), courbes de l'état du paiement, du trafic et de la latence de l'API sur 15 min avec les incidents en surbrillance, chronologie de chaque incident (action, preuve du canary). Rafraîchie toutes les 2 s.

- Service FastAPI (`app/`) + site React (`ui/`) dans une seule image, un seul port : `http://127.0.0.1:8090` (`SUPERVISION_PORT`, `ADMIN_BIND`). **Pas derrière le WAF** : la supervision ne doit pas être joignable par le trafic client.
- **Lecture seule** : uniquement des `GET` (`/api/status`, `/api/history`). Il lit le canary (`/metrics`), la remédiation (`/v1/incidents`, avec `engine_token` côté serveur : le navigateur ne le voit jamais) et Prometheus (`query_range`).
- **Honnêteté de l'état** : sans sonde fraîche (`PROBE_STALE_S`) ou si le canary est injoignable, le bandeau affiche « État inconnu », jamais « sain ». Si la supervision elle-même est coupée, la page l'affiche.
- Dev du site : `cd supervision/ui && npm install && npm run dev` (port 5175, `/api` relayé vers `DEV_SUPERVISION_URL`).
- Limite assumée : pas d'authentification (POC, accès local). Le token `engine_token` est monté dans ce service : le code n'appelle que des routes de lecture.

## Tester le parcours de paiement

Procédure complète (tests, parcours à la main, simulation d'incident) : [`doc/AUTH-FRONTEND.md`](../doc/AUTH-FRONTEND.md#comment-tester). `DEV_AUTH_URL` (défaut `http://localhost:8001`) règle la cible de `/auth` du serveur de dev.

## Contrats portés par DEV

- **JWT** émis par `auth`, lu par `api` : contrat dans [`api/README.md`](api/README.md#contrat-avec-auth).
- **`remediation`** : interfaces (a) et (b) dans [ARCHITECTURE](../doc/ARCHITECTURE.md). Deux executors (`local`, `ssh`) derrière la même interface, choisis par `REMEDIATION_MODE`.
- **`canary`** : `POST /verify` = transaction complète via le WAF + `GET /v1/ledger/check`.
