# PROJECT RESILIENCE-ALPHA — groupe M2-G4

Plateforme de paiement **fictive** qui subit une attaque (saturation de l'API), la détecte par ML, se répare seule, puis **prouve** la reprise en rejouant une transaction. Workshop EPSI BAC+5, aucune donnée réelle.

**Mono-hôte par défaut** (dev et secours : tout sur une machine, aucune VM requise) ; **multi-machines en cible** (cloisonnement front / back / ops, optionnel). Détails : [`doc/ARCHITECTURE.md`](doc/ARCHITECTURE.md). Avancement et priorités : [`doc/ROADMAP.md`](doc/ROADMAP.md).

## Démarrer (mono-hôte, sans VM ni clé SSH)

Prérequis : Docker + Compose v2, Git, un shell bash (Git Bash sous Windows).

```bash
./scripts/init-local.sh              # crée .env et des secrets locaux aléatoires dans .secrets/ (ignoré par git)
./scripts/compose.sh up -d --build   # lance la plateforme sur cette machine
./scripts/compose.sh ps              # état des services
./scripts/compose.sh logs -f api     # logs d'un service
./scripts/compose.sh down            # arrête (les données restent)
```

`compose.sh` est `docker compose` avec les bons fichiers, choisis par `ROLES` et `REMEDIATION_MODE` dans `.env`. Si le port 8000 est pris : `API_PORT=18000` dans `.env`.

> Seuls `db`, `api`, `auth`, `frontend` et `canary` existent pour l'instant (voir la roadmap) : `up --build` échoue sur les autres, qui n'ont pas encore de code. En attendant : `./scripts/compose.sh up -d --build db api auth frontend`, puis [tester le parcours de paiement](doc/AUTH-FRONTEND.md#comment-tester).

Multi-machines, secrets partagés (SOPS), mode de remédiation `ssh` : voir [`doc/ARCHITECTURE.md`](doc/ARCHITECTURE.md) et [`cyber/README.md`](cyber/README.md).

## Accès

| Quoi | Adresse | Exposition |
|---|---|---|
| Plateforme (via le WAF) | `http://<ip-hôte>:8080` | réseau — seul point d'entrée |
| Grafana | `http://127.0.0.1:3000` | local (`ADMIN_BIND`) |
| Assistant RAG | `http://127.0.0.1:8501` | local (`ADMIN_BIND`) |

Base de données, remédiation et secrets ne sont jamais publiés.

## Organisation du dépôt

| Dossier | Domaine | Contenu |
|---|---|---|
| [`dev/`](dev/README.md) | DEV | `api`, `auth`, `frontend`, `canary` (faits) ; `remediation` (à faire) |
| [`ia/`](ia/README.md) | IA | `detector` (ML), `assistant` (RAG) |
| [`cyber/`](cyber/README.md) | CYBER | `waf`, `attack`, secrets |
| [`infra/`](infra/README.md) | INFRA | `compose/`, `ansible/`, `monitoring/` |
| `doc/` | GOUVERNANCE | documentation (ci-dessous), puis EBIOS, PCA/PRA, NIS2/DORA |
| `scripts/`, `.github/` | INFRA | outils, CI/CD |

Un dossier de service n'existe que lorsqu'il contient du code.

## Documentation

| Document | Rôle |
|---|---|
| [`doc/ROADMAP.md`](doc/ROADMAP.md) | Pilotage : qui fait quoi, jour par jour, cœur vs bonus |
| [`doc/ARCHITECTURE.md`](doc/ARCHITECTURE.md) | Services, boucle de reprise, contrats entre domaines, modes de déploiement, sécurité |
| [`doc/STACK.md`](doc/STACK.md) | Contraintes du sujet et rôle de chaque outil chez nous |
| [`doc/AUTH-FRONTEND.md`](doc/AUTH-FRONTEND.md) | Fiche auth + frontend : ce qui est fait, comment le tester, ce qui reste |
| [`doc/GITHUB.md`](doc/GITHUB.md) | Règles de branches / PR et commandes Git |
| [`doc/CONCEPTS.md`](doc/CONCEPTS.md) | Glossaire |
| [`CLAUDE.md`](CLAUDE.md) | Consignes pour les sessions d'assistant IA |
