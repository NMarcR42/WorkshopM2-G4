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

## Contrats portés par DEV

- **JWT** émis par `auth`, lu par `api` : contrat dans [`api/README.md`](api/README.md#contrat-avec-auth).
- **`remediation`** : interfaces (a) et (b) dans [ARCHITECTURE](../doc/ARCHITECTURE.md). Deux executors (`local`, `ssh`) derrière la même interface, choisis par `REMEDIATION_MODE`.
- **`canary`** : `POST /verify` = transaction complète via le WAF + `GET /v1/ledger/check`.
