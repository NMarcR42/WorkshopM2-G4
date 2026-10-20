# Contrats d'interface Infra ↔ Dev / IA / Cyber

Ce que l'infrastructure attend de chaque pilier, et ce qu'elle lui fournit. Si un point ne vous convient pas, on en discute **avant** de coder.

## Pour le DEV (SI de paiement, moteur de remédiation, dashboard)

### Services métier (vm-app)

| Service | Port interne | Préfixe d'URL (via WAF) | Santé |
|---|---|---|---|
| frontend (React) | 8080 | `/` | `GET /` → 200 |
| api (FastAPI) | 8000 | `/api/...` (le préfixe est **conservé**) | `GET /api/health` → 200 |
| auth (JWT) | 8001 | `/auth/...` (préfixe conservé) | `GET /auth/health` → 200 |

- Le gateway nginx (`ra-gateway`) route `/api/` vers api et `/auth/` vers auth. Le frontend n'a pas à faire de proxy.
- **Base** : `DB_HOST=postgres DB_PORT=5432 DB_NAME=payments DB_USER=payments`, mot de passe dans le **fichier** `DB_PASSWORD_FILE=/run/secrets/postgres_password`. Jamais en variable en clair.
- **Vault** : `VAULT_ADDR=http://192.168.1.151:8200`.
- **Logs** : sur stdout, en **JSON** si possible (`level`, `msg`, `request_id`, `client_ip`). Alloy les envoie à Loki automatiquement.
- **Métriques** : `GET /metrics` au format Prometheus, avec au minimum `http_requests_total{method,route,status}` et `http_request_duration_seconds`. En FastAPI : `prometheus-fastapi-instrumentator`. Elles sont collectées automatiquement grâce aux labels déjà présents dans le Compose (`prometheus.scrape`, `prometheus.port`, `prometheus.network`).
- **Transaction de contrôle** : `POST /api/synthetic/transaction` avec `Authorization: Bearer <synthetic_probe_token>` et un corps `{"amount":1.0,"currency":"EUR","label":"..."}`. Elle doit traverser auth, api et base, puis répondre `200 {"status":"ok", ...}`. C'est **la preuve de reprise** utilisée par les sondes et par la vérification post-remédiation.
- **Livraison des images** : construire sur vm-app (`docker build -t ra/api:dev .`), indiquer les tags dans `app_images`, passer `app_placeholder: false`, puis lancer `ansible-playbook playbooks/site.yml --limit app`.

### Moteur de remédiation (vm-ops :8080)

- Image : `FROM ra/remediation-runner`, qui contient Ansible, `community.proxmox` et le client SSH. Elle n'a pas de socket Docker.
- Entrée : `POST /api/v1/alerts`, au format **webhook Alertmanager v4**. Il faut refuser toute requête sans `Authorization: Bearer <alert_webhook_token>` (fichier `/opt/resilience/ops/keys/alert_webhook_token`).
- Décision : lire `labels.remediation` (`restart`, `recreate`, `block_ip`, `isolate`, `restore_db`, `rollback_vm`, `auto`), `labels.service` et, pour `block_ip`, **`labels.client_ip`** (IP de l'attaquant, extraite des logs BunkerWeb).
- Action : `ansible-playbook remediation/<action>.yml -e service=<service>` (ou `-e ip=<ip>`), lancé depuis `/work` (le dépôt `ansible/` monté en lecture seule).
- Suivi : la dernière tâche affiche `SERVICE RÉTABLI — ...` et le code de retour vaut 0 si la vérification métier passe. Prévoir aussi un anti-rebond, pour ne pas relancer la même action pendant une remédiation en cours.
- Montages : `/opt/resilience/repo/ansible:/work:ro` et `/opt/resilience/ops/keys:/opt/resilience/ops/keys:ro` (voir le bloc commenté dans `roles/ops/templates/docker-compose.yml.j2`).

### Dashboard (vm-ops :5173)

- Données disponibles : API Prometheus `http://192.168.1.142:9090/api/v1/query`, API Loki `http://192.168.1.142:3100/loki/api/v1/query_range`, API Alertmanager `:9093/api/v2/alerts`.
- Requêtes utiles : `probe_success`, `ALERTS{alertstate="firing"}`, `{syslog_identifier="ra-remediate"}`.

## Pour l'IA

- **Ollama** : `http://192.168.1.152:11434`, joignable depuis vm-ops uniquement (pare-feu). Les modèles se déclarent dans `ollama_models` (<= 8 milliards de paramètres).
- **Détecteur ML** : servir `GET :8500/metrics` sur vm-ia avec la jauge `ra_anomaly_score{service="api",scenario="dos|injection|exfiltration"}` comprise entre 0 et 1. Au-delà de 0.8 pendant 30 s, l'alerte `AnomalieDetecteeML` part vers la remédiation.
- **Données d'entraînement** : API Prometheus (`/api/v1/query_range`) et Loki (`/loki/api/v1/query_range`) sur vm-obs.
- **RAG** : les documents de `docs/` (procédures, architecture, PCA/PRA) constituent le corpus. L'assistant reste **en lecture seule** : aucune clé SSH, aucun jeton.

## Pour la CYBER

- **WAF** : **BunkerWeb 1.6.16** (ModSecurity + CRS v4, bad behavior, limitation de débit). Bannissements via `bwcli`, utilisé par `ra-remediate block-ip|unblock-ip|bans`. Logs sur stdout, donc dans Loki.
- **Règles SIEM existantes** : `ansible/roles/obs/files/loki-rules/securite.yml`. À compléter, et à dupliquer côté Graylog si la VM-SIEM est retenue.
- **Secrets** : SOPS + age (dépôt) et Vault (applicatif, vm-ops:8200, à initialiser et désceller : `docker exec -it ra-vault vault operator init`).
- **Privilèges de la remédiation** : compte `remediator` limité à `ra-remediate`, clé acceptée uniquement depuis vm-ops, jeton Proxmox limité à la VM 200. Chaque action est tracée dans le journal.
- **Attaques** : la cible est **pfSense WAN 192.168.137.2:443** (après la phase 10) ; d'ici là, `https://192.168.1.24`.
