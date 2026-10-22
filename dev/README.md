# dev

Services métier et moteur de reprise : `api`, `auth`, `frontend`, `canary`, `remediation`, `supervision`. Rôle de chacun : [Services](../doc/ARCHITECTURE.md#services). Avancement : [roadmap](../doc/ROADMAP.md).

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

**Contrôle facial (`FACE_ENFORCE`)** : `false` par défaut, `auth` se comporte comme avant. À `true`, `POST /login` exige l'en-tête `X-Face-Token` (renvoyé par le serveur de reconnaissance, voir [`ia/README-face.md`](../ia/README-face.md)) et le valide auprès de ce serveur (`POST {FACE_SERVICE_URL}/auth/confirm`, clé de service = secret `face_service_key`). Token absent ou refusé : 403 ; serveur de reconnaissance injoignable : 503 propre, sans JWT (refus par défaut). Le compte technique `canary` est exempté. Détail et test : [`doc/AUTH-FRONTEND.md`](../doc/AUTH-FRONTEND.md).

## frontend

Application React + Tailwind (Vite), sobre. Parcours : **login en 3 étapes** (identifiant → reconnaissance faciale → mot de passe) → tableau de bord (solde total, comptes) → **boutique** (4 articles fictifs, « Payer ») → **historique des transactions** (date, libellé, montant, statut) ; un « virement libre » reste disponible. La vue du jury est un autre service : [`supervision`](#supervision).

- **Login et plan B** : `VITE_FACE_MODE` = `mock` (simulation, défaut), `api` (serveur de reconnaissance réel, `VITE_FACE_BASE`, défaut `/face`) ou `off` (étape sautée). Une panne du serveur facial (caméra introuvable, service injoignable) bascule automatiquement sur le mot de passe seul ; un visage refusé ou un compte bloqué n'ouvre pas le plan B tout seul. Avec `FACE_ENFORCE=true` côté `auth`, le plan B est refusé : repasser `FACE_ENFORCE=false`.
- **Boutique** : chaque paiement utilise l'endpoint existant `POST /v1/transactions` vers `VITE_MERCHANT_ACCOUNT` (défaut `ACC-MERCHANT`), avec le prix de l'article. L'API n'a pas de champ libellé : le nom de l'article est gardé dans le navigateur (`localStorage`) pour l'historique ; sans lui, l'historique affiche « Virement A → B ».
- Aucun identifiant de démo n'est affiché à l'écran.
- Appelle `/api/…`, `/auth/…` et `/face/…` sur la même origine, donc **toujours via le WAF** et le gateway ; préfixes réglables à la construction par `VITE_API_BASE`, `VITE_AUTH_BASE` et `VITE_FACE_BASE`. La route `/face/` vers le serveur de reconnaissance est à déclarer côté WAF/gateway.
- Délai de 8 s par requête (20 s pour la reconnaissance faciale, la caméra reste allumée quelques secondes), échec affiché clairement, `Idempotency-Key` conservée tant que la réponse est incertaine : on peut réessayer sans payer deux fois.
- Ne parle ni à `remediation`, ni au `detector`, ni à l'`assistant` ; seul service IA joint : le serveur de reconnaissance faciale.
- Pas de `/metrics` : l'observabilité métier est côté API.

## supervision

Vue du jury, en lecture seule : agrège l'état du paiement (`canary`), les incidents (`remediation`) et l'historique (Prometheus). Service FastAPI qui sert aussi le site compilé (`ui/`, React + Tailwind). Routes : `GET /api/status`, `/api/alerts`, `/api/remediation-log`, `/api/history`, `/health`, `/metrics`. Il n'expose que des `GET` et n'appelle jamais une route qui agit ; le navigateur ne parle qu'à lui, les adresses et tokens des services de contrôle restent côté serveur.

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

Reçoit les alertes Alertmanager (contrat infra), choisit l'action, l'exécute (interface (b)) et ne conclut qu'avec la preuve du canary.

Pour chaque alerte `firing` (`POST /api/v1/alerts`, webhook Alertmanager v4, Bearer = secret `alert_webhook_token`, réponse 200 immédiate, traitement en arrière-plan) :
1. **Mapping** (`app/alerts.py`, même table que le `receiver.py` de l'infra) : `labels.remediation` ∈ `restart|recreate|isolate|block_ip|restore_db|rollback_vm|auto` ; `auto` : `dos`→`block_ip`, `injection`→`restart`, `exfiltration`→`isolate`. `labels.service` (défaut `api`, liste `ALLOWED_SERVICES`), `labels.client_ip` pour `block_ip`.
2. **Dédoublonnage / anti-rebond** : même alerte (fingerprint + startsAt), incident déjà en cours, résolu depuis moins de `REMEDIATION_COOLDOWN_S` (30 s), ou même (action, cible) relancée avant `ACTION_COOLDOWN_S` (90 s) → ignorée.
3. **Garde faux positif** : alerte `auto` (hors `block_ip`) et canary qui passe → `RESOLVED` sans rien toucher (`AUTO_VERIFY_FIRST=0` pour désactiver).
4. **Escalade** : action demandée → (`block_ip`: `restart` → `recreate` ; `restart`: `recreate`). `rollback_vm`, `restore_db`, `isolate` ne s'enchaînent jamais seuls. Après chaque action, on attend que `POST /verify` passe (`VERIFY_TIMEOUT_S`, 30 s). Premier succès → `RESOLVED` (`resolved_by` = l'action) ; liste épuisée → `UNRESOLVED` (intervention humaine, visible).
5. **Journal** : `incident.json` et `<action>.json` par incident, dans le volume `incidents` ; lisibles par `GET /v1/incidents` et `/v1/incidents/{id}` (Bearer `ENGINE_TOKEN`, à défaut `alert_webhook_token`). Un incident interrompu par un redémarrage est marqué `UNRESOLVED`.

Garde-fous : service en liste fermée ; IP validées, jamais dans `PROTECTED_CIDRS`, blocage expiré après `BLOCK_TTL_S` ; aucune valeur d'alerte n'atteint un shell. Métriques : `remediation_incidents_total{status}`, `remediation_actions_total{action,result}`, `remediation_recovery_seconds`, `remediation_incidents_active`.

Executors (`REMEDIATION_MODE`) : `ansible` (défaut ; alias `ssh`) lance `ansible-playbook remediation/<action>.yml -e service=…|ip=…` depuis `ANSIBLE_WORKDIR` (`/work`), succès = code 0 **et** « SERVICE RÉTABLI » dans la sortie ; `local` : docker-proxy (`restart`/`recreate` = redémarrage) et `blocklist.txt` du WAF, `isolate`/`restore_db`/`rollback_vm` refusés. Test local : `REMEDIATION_MODE=local ALERT_WEBHOOK_TOKEN=… CANARY_URL=…` puis `curl -H "Authorization: Bearer …" -d '{"alerts":[{"status":"firing","labels":{"remediation":"restart","service":"api"}}]}' localhost:8000/api/v1/alerts`.

- **JWT** émis par `auth`, lu par `api` : contrat dans [`api/README.md`](api/README.md#contrat-avec-auth).
- **`remediation`** : entrée webhook Alertmanager et interface (b) dans [ARCHITECTURE](../doc/ARCHITECTURE.md). Deux executors (`local`, `ansible`) derrière la même interface, choisis par `REMEDIATION_MODE`.
- **`canary`** : `POST /verify` = transaction complète via le WAF + `GET /v1/ledger/check`.
