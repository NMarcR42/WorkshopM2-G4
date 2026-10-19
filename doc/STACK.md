# Stack technique

Ce que chaque outil fait **chez nous**, et les pièges déjà rencontrés. Les définitions générales sont dans [CONCEPTS](CONCEPTS.md), l'architecture dans [ARCHITECTURE](ARCHITECTURE.md).

## Contraintes du sujet (non négociables)

- 5 domaines obligatoires : DEV, INFRA, IA, CYBER, GOUVERNANCE.
- Backend : Node.js, Python/FastAPI ou Go → **FastAPI partout**. Front : **React + Tailwind**.
- Un seul `up` (Docker Compose), Ansible, Prometheus + Grafana + Loki. **Pas d'Elastic.**
- ML pour la détection (**aucun seuil codé en dur**) ; assistant RAG local avec Ollama + LangChain, modèle ≤ 8B, **sans accès privilégié** et sans pilotage de la remédiation.
- WAF devant l'API, secrets avec Vault ou SOPS (**aucun secret en clair dans le dépôt**), SIEM/SOC léger.
- Attaque retenue : saturation HTTP de l'API depuis un PC distinct. Données 100 % fictives, périmètre offensif limité à notre SI.

## Outils

| Outil | Rôle chez nous | Où | À savoir |
|---|---|---|---|
| **FastAPI** | `api`, `auth`, `canary`, `remediation` | `dev/` | Endpoints synchrones (`def`) : sous flood, le pool de threads et de connexions sature de façon visible, c'est voulu. Chaque service expose `/health` (process) et `/metrics`. `api` sert de modèle. |
| **PostgreSQL** | Comptes et transactions | `infra/compose/back.yml` | Jamais publié. Schéma créé par l'API au démarrage (pas de migrations). |
| **Docker Compose** | Définit la plateforme ; **un fichier par rôle de machine** | `infra/compose/` | Toujours via `./scripts/compose.sh` : il choisit les fichiers selon `ROLES` et `REMEDIATION_MODE`. Un fichier compose seul ne marche pas pour la plateforme complète. |
| **Ansible** | Exécuteur des actions de remédiation en mode `ssh` ; peut aussi déployer | `infra/ansible/` | Un playbook = une action de la liste fermée. Groupes d'inventaire = noms de services. Inutile en mode `local`. |
| **docker-proxy** | Donne à `remediation` le droit de redémarrer, et rien d'autre (mode `local`) | `infra/compose/remediation-local.yml` | `ALLOW_RESTARTS` ne marche que si `POST=1` ; `CONTAINERS` doit rester à 0 sinon la création de conteneurs s'ouvre. Testé. |
| **Prometheus** | Métriques (API, canary, cAdvisor) ; **source du détecteur** | `infra/monitoring/` | Cibles dans `targets.yml` (noms de services en mono-hôte, IP en multi-machines). |
| **Loki + Promtail** | Logs de tous les conteneurs = **SIEM léger** ; sert à désigner l'IP attaquante | `infra/monitoring/promtail.yml` | Un Promtail par machine. Les logs de l'API sont en JSON avec `client_ip`. |
| **Grafana** | Tableau de bord du jury (état avant / pendant / après, incidents) et alertes | `infra/monitoring/grafana/` | Local uniquement (`ADMIN_BIND`). |
| **cAdvisor** | CPU/mémoire par conteneur, une des features du détecteur | `infra/compose/agents.yml` | — |
| **scikit-learn** | Isolation Forest du détecteur | `ia/detector/` | Entraîné sur du trafic normal généré ; modèle figé dans le dépôt pour une démo reproductible. |
| **Ollama + LangChain** | Assistant RAG pour les opérateurs, sur les documents de `doc/` | `ia/assistant/` | Modèle ~3B par défaut (`OLLAMA_MODEL`), le plus lent à démarrer : hors du chemin critique. |
| **nginx + ModSecurity (CRS)** | WAF unique point d'entrée ; applique la liste de blocage | `cyber/waf/` | Tag d'image à épingler après le premier pull. |
| **SOPS + age** | Secrets chiffrés pour les déploiements partagés | `cyber/` | Pas nécessaire en dev local (`init-local.sh`). |
| **GitHub Actions** | CI sur chaque PR ; déploiement manuel sur runner self-hosted | `.github/workflows/` | Voir [GITHUB](GITHUB.md). |
| **React + Tailwind** | Vue paiement et vue supervision | `dev/frontend/` | Passe par le WAF, jamais directement par l'API. |

## Pièges Windows (Git Bash / Docker Desktop)

- Git Bash réécrit les chemins `-v /var/run/docker.sock:…` : écrire `//var/run/docker.sock` ou passer par compose.
- Le port 8000 de l'hôte est souvent pris : `API_PORT=18000` dans `.env`.
- Les scripts sont en bash : les lancer depuis Git Bash ou WSL.
