# Auth et frontend : ce qui a été fait, comment tester, ce qui reste

Fiche de suivi de la brique « parcours de paiement » (login → comptes → paiement). Les conventions des services sont dans [`dev/README.md`](../dev/README.md), le routage du WAF dans [ARCHITECTURE](ARCHITECTURE.md#routage-de-lentrée-waf).

## En deux phrases

Un utilisateur se connecte sur le site, `auth` lui donne un jeton (JWT), et le site s'en sert pour lire ses comptes et payer via l'API. Tout passe par le WAF, jamais directement par les services.

```
navigateur → WAF :8080 ─┬─ /auth/…  → auth     (login, émet le jeton)
                        ├─ /api/…   → api      (comptes, paiements, vérifie le jeton)
                        └─ le reste → frontend (la page web)
```

## Ce qui a été fait

| Brique | Ce que c'est | Où |
|---|---|---|
| **auth** | `POST /login` : vérifie le mot de passe et renvoie un JWT (contrat de l'API : `sub`, `exp`, `role`). Comptes de démo, pas de base de données. Journalise les échecs de login pour le SIEM. | `dev/auth/` |
| **frontend** | Site React + Tailwind sobre : connexion, mes comptes, nouveau paiement, résultat succès/échec, dernières transactions. | `dev/frontend/` |
| **API** (ajout) | Nouvelle route `GET /v1/accounts` : liste les comptes de l'utilisateur connecté. Sans elle, le site aurait dû deviner les numéros de compte. | `dev/api/app/routes.py` |
| **API** (correction) | Après un redémarrage de la base, la 1ʳᵉ requête échouait en 503 (connexion morte dans le pool). Le pool teste maintenant chaque connexion. Important pour la vérification de reprise. | `dev/api/app/db.py` |
| **Composes** | `frontend` reçoit les préfixes d'appel ; `auth` n'a plus accès à la base ; le WAF reçoit `AUTH_URL` et `FRONTEND_URL`. | `infra/compose/front.yml`, `back.yml` |
| **CI** | Les tests des services comme `auth` installent maintenant `pytest` et `httpx`. | `.github/workflows/ci.yml` |

Choix à connaître :
- **Comptes de démo (fictifs)** : `alice / alice-demo`, `bob / bob-demo` (clients), `ops / ops-demo` (rôle `operator`). Les mots de passe sont hachés dans `dev/auth/app/users.json` ; `ops` est utilisable par n'importe qui atteignant la plateforme, acceptable pour un POC.
- **Le jeton vit 30 min** (`AUTH_TOKEN_TTL_S`) et est gardé dans `sessionStorage` : il disparaît à la fermeture de l'onglet.
- **Pas de double paiement** : le site envoie une `Idempotency-Key` et la garde tant que la réponse est incertaine (timeout, 503), donc « Réessayer » ne débite pas deux fois.
- **Le site coupe après 8 s** (`VITE_REQUEST_TIMEOUT_MS`) pour afficher un échec clair pendant l'attaque au lieu de rester bloqué.
- **Le site ne parle jamais** à `remediation`, `detector` ni `assistant`.

## Comment tester

### 1. Tests automatiques

```bash
cd dev/auth && python -m venv .venv && source .venv/bin/activate    # Windows : .venv\Scripts\activate
pip install -r requirements-dev.txt && pytest -q                    # 7 tests
```

Pour l'API (17 tests, dont 8 qui ont besoin d'une base) : voir [`dev/api/README.md`](../dev/api/README.md#développer). Le site se compile avec `cd dev/frontend && npm ci && npm run build`.

### 2. Parcours complet à la main

Il n'y a pas encore de WAF : le serveur de dev Vite fait le même routage à sa place.

```bash
./scripts/init-local.sh                                    # 1re fois
echo "API_PORT=18000" >> .env                              # seulement si le port 8000 est pris
./scripts/compose.sh up -d --build db api auth frontend
cd dev/frontend && npm install                             # 1re fois
DEV_API_URL=http://localhost:18000 npm run dev             # noter l'URL affichée
```

Vite prend le port 5173, ou le suivant s'il est occupé : **ouvrir l'URL affichée dans le terminal** (vérifier que l'onglet s'intitule « Paiement (démo fictive) »).

| Étape | Action | Résultat attendu |
|---|---|---|
| Connexion | `alice` / `alice-demo` | Écran « Mes comptes » avec `ACC-ALICE` à 1000.00 EUR |
| Mauvais mot de passe | `alice` / `faux` | « Identifiants invalides » |
| Paiement | 10.00 vers `ACC-MERCHANT` | « Paiement accepté », solde 990.00, ligne dans l'historique |
| Solde insuffisant | 99999 vers `ACC-MERCHANT` | « Paiement échoué : Solde insuffisant » |
| Compte d'un autre | Le formulaire n'offre que les comptes d'alice ; avec curl, débiter `ACC-BOB` donne 403 | « Ce compte ne vous appartient pas » |

### 3. Simuler l'incident (ce que verra le jury)

```bash
docker stop resilience-db-1       # la base tombe
```

Payer dans le site : « Paiement échoué : Service momentanément indisponible. Vous pouvez réessayer… ».

```bash
docker start resilience-db-1      # la base revient (compter ~10 s)
```

Cliquer de nouveau sur « Payer » **sans modifier le formulaire** : le paiement passe, une seule fois. Autre vérification : l'API arrêtée (`docker stop resilience-api-1`) fait afficher « Service injoignable » ou « Le service ne répond pas ».

### 4. Contrôles côté serveur (curl)

À lancer sur l'URL de Vite (ici `5173`) :

```bash
B=http://127.0.0.1:5173
TOK=$(curl -s -X POST $B/auth/login -H 'Content-Type: application/json' \
      -d '{"username":"alice","password":"alice-demo"}' | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
curl -s $B/api/v1/accounts -H "Authorization: Bearer $TOK"     # les comptes d'alice
curl -s -o /dev/null -w '%{http_code}\n' $B/api/v1/accounts    # 401 sans jeton
```

Côté logs : `./scripts/compose.sh logs auth` montre `login_ok` / `login_failed` (utiles au SIEM), `logs api` montre `client_ip` pour chaque requête.

### Pièges connus

- Port 8000 pris sur la machine : `API_PORT=18000` dans `.env` et `DEV_API_URL=http://localhost:18000`.
- Vite change de port sans prévenir si 5173 est pris : lire l'URL affichée.
- Après `docker stop` puis `start` de la base, attendre qu'elle soit « healthy » (`./scripts/compose.sh ps`).

## Login en 3 étapes (identifiant → visage → mot de passe)

Côté front : `Login.jsx`, `FaceStep.jsx`, `api.js`. Côté IA : serveur `ia/face/` sur le PC hôte (lancement et contrat complet : [`ia/README-face.md`](../ia/README-face.md)). Le serveur lit lui-même la caméra USB : le front n'envoie aucune image, il appelle `POST /auth/identify {user}` et attend le verdict.

Le mode se fixe à la construction par `VITE_FACE_MODE` : `mock` (défaut, simulation affichée à l'écran), `api` (serveur IA réel), `off` (étape sautée). Adresse du serveur : `VITE_FACE_BASE` (défaut `/face`, à router vers `hôte:8600` en retirant le préfixe ; en dev, proxy Vite vers `DEV_FACE_URL`, défaut `http://localhost:8600`). Sans proxy : mettre l'URL complète et déclarer l'origine du front dans `CORS_ORIGINS` côté IA.

- **Mot de passe** : vérifié par `auth` (`/auth/login`, le JWT sert à l'API). Le `token` visage est envoyé en `X-Face-Token`.
- **Plan B** : panne (caméra introuvable 503, serveur IA injoignable) → bascule automatique au mot de passe seul, avec avertissement. Visage refusé / compte bloqué (429) → pas de bascule automatique, message du serveur ; bouton manuel « continuer avec le mot de passe seul ». Plan B global le jour J : reconstruire avec `VITE_FACE_MODE=off`.
- **Contrôle côté serveur (`FACE_ENFORCE`)** : `false` par défaut, `auth` ignore le visage (comportement historique, aucun service IA requis). `true` : `/auth/login` exige `X-Face-Token`, le valide auprès de l'IA par `POST {FACE_SERVICE_URL}/auth/confirm` (clé de service = secret `face_service_key`, à copier dans `SERVICE_KEY` côté IA ; usage unique, lié à l'utilisateur) et ne délivre le JWT qu'ensuite. Refus : 403 token absent/expiré, 503 IA injoignable (fail closed, pas de plantage). Le compte technique `canary` est exempté. Cela pilote aussi les LED (vert/rouge selon le mot de passe). En `true`, le plan B « mot de passe seul » est refusé : pour l'activer le jour J, repasser `FACE_ENFORCE=false`.
- **À faire** : route `/face/` au WAF ; `./scripts/init-local.sh` à relancer sur les clones existants (nouveau secret `face_service_key`, et à ajouter à SOPS).

## Ce qui reste à faire

| À faire | Qui | Détail |
|---|---|---|
| **WAF** | CYBER | Router `/api/` → API et `/auth/` → auth **en retirant le préfixe**, le reste → frontend, et poser `X-Forwarded-For`. Sans lui, le parcours ne marche qu'avec le proxy de dev. Variables déjà prévues : `BACKEND`, `AUTH_URL`, `FRONTEND_URL`. |
| **Test dans un vrai navigateur** | DEV | Le parcours a été validé par requêtes HTTP et le site se compile, mais l'interface n'a pas été cliquée dans un navigateur : à faire une fois. |
| **Secret `canary_password`** | CYBER | Fait côté code (voir `dev/README.md#canary`). Reste à ajouter la clé `canary_password` dans `cyber/secrets/secrets.enc.yaml` (SOPS). |
| **Compte `ops`** | CYBER | Décider si le mot de passe de démo de `ops` reste public ou passe en secret avant la démo. |
| **Rate limiting du login** | CYBER | À faire dans le WAF : `/login` coûte du CPU (hash) et est une cible naturelle du flood. |
