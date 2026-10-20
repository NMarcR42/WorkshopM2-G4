# api

API métier FastAPI : virements fictifs entre comptes fictifs, PostgreSQL, JWT. Conventions communes : [`dev/README.md`](../README.md).

## Choix à connaître (pour le jury)

- **JWT vérifié localement** (secret partagé avec `auth`) : une panne d'`auth` n'arrête pas les paiements des utilisateurs déjà connectés.
- **Virement atomique** : les deux comptes sont verrouillés (`FOR UPDATE`, ordre fixe), puis débit + crédit + ligne `transactions` dans une seule transaction SQL.
- **`Idempotency-Key`** : rejouer la même requête renvoie la transaction existante (200 au lieu de 201), utile quand le canary ou un client réessaie après un timeout.
- **`GET /v1/ledger/check`** : vérifie que `solde = solde initial + crédits − débits` pour chaque compte. C'est la détection de « données incohérentes » du sujet, appelée par la vérification de reprise.
- **Dégradation propre** : base indisponible → `503` + `Retry-After`. L'API démarre sans base et s'y reconnecte seule. Pool de connexions borné (`DB_POOL_MAX`, timeout 3 s) : sous flood, l'API sature de façon visible (latence, 503) au lieu de s'effondrer.
- `/health` = le process répond ; `/ready` = la base répond. Aucun des deux ne prouve que le métier marche : seul le **canary** le prouve.

## Endpoints

| Méthode | Route | Rôles | Rôle |
|---|---|---|---|
| POST | `/v1/transactions` | client, canary, operator | Crée un virement (`Idempotency-Key` optionnel). Un `client` ne débite que ses comptes. |
| GET | `/v1/transactions/{id}` | idem | Lecture (un `client` ne voit que les siennes) |
| GET | `/v1/transactions?limit=` | idem | Liste récente |
| GET | `/v1/accounts` | idem | Liste des comptes : ceux du client connecté (`owner = sub`), tous pour `operator` / `canary` |
| GET | `/v1/accounts/{id}` | idem | Solde (un `client` ne voit que les siens) |
| GET | `/v1/ledger/check` | canary, operator | Cohérence comptable |
| GET | `/health` `/ready` `/metrics` | public | Sondes et métriques Prometheus |

Documentation interactive : `/docs`. Comptes de départ : `ACC-ALICE`, `ACC-BOB`, `ACC-MERCHANT`, `ACC-CANARY-A`, `ACC-CANARY-B`.

## Contrat avec `auth`

JWT HS256, secret = `jwt_secret`. Claims obligatoires : `sub` (identifiant, égal au `owner` des comptes), `exp`, `role` ∈ `client | operator | canary`.

## Observabilité

- Métriques : `http_requests_total{method,route,status}`, `http_request_duration_seconds{route}`, `http_requests_in_flight`, `payment_transactions_total{status}`.
- Logs JSON (un par requête) avec `client_ip`, lue dans `X-Forwarded-For` posé par le WAF : c'est ce qui permet de désigner l'IP attaquante.

## Développer

```bash
cd dev/api
python -m venv .venv && source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest -q                                                # tests sans base (ceux qui en ont besoin sont ignorés)

# tests complets, avec une base jetable :
docker run -d --name pgtest -e POSTGRES_USER=payments -e POSTGRES_PASSWORD=test -e POSTGRES_DB=payments -p 55432:5432 postgres:16-alpine
TEST_DB_HOST=127.0.0.1 TEST_DB_PORT=55432 DB_PASSWORD=test pytest -q
docker rm -f pgtest
```

Dans Docker, depuis la racine du dépôt (après `./scripts/init-local.sh`) :

```bash
./scripts/compose.sh up -d --build db api
JWT_SECRET_FILE=.secrets/jwt_secret python dev/api/tools/make_token.py canary canary   # jeton de test
```

## Limites assumées

Pas de migrations (schéma créé au démarrage), pas de pagination par curseur, pas de rate limiting (rôle du WAF). `X-Forwarded-For` suppose que seul le WAF atteint l'API (filtrage réseau).
