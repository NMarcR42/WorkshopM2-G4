# ia

`detector` (ML), `assistant` (RAG) et le serveur de **reconnaissance faciale** (`face`). Avancement : [roadmap](../doc/ROADMAP.md).

## detector

- Isolation Forest sur des fenêtres de 10 s (req/s, latence p95, taux de 5xx, CPU), lues dans Prometheus.
- **Pas de seuil codé en dur** : le modèle est entraîné sur du trafic normal généré par nos soins ; le seuil de décision vient de la distribution des scores d'entraînement.
- Sortie : jauges Prometheus sur `/metrics` (`anomaly_score`, `anomaly_flag`, `anomaly_consecutive_windows`), `GET /status` et `GET /health`. Une anomalie est signalée après `FENETRES_REQUISES` (3) fenêtres anormales de suite. La remédiation est déclenchée par Alertmanager ; l'IP suspecte vient des logs du WAF, pas du modèle. Les routes `/simulate/attack/on|off` servent à tester sans plateforme.
- À documenter pour le dossier : données utilisées, préparation, modèle retenu, résultats, limites (faux positifs).
- Le modèle entraîné est **versionné dans le dépôt** (démo reproductible) ; les données brutes volumineuses sont ignorées (`ia/detector/data/raw/`).

## face (reconnaissance faciale)

Serveur FastAPI exécuté sur le **PC hôte** (il lit la caméra USB, port 8600) : `ia/face/`, modèles YuNet + SFace dans `ia/models/face/`. Le site appelle `POST /auth/identify {user}` ; si le visage est reconnu, le serveur renvoie un token à usage unique, que `auth` valide ensuite via `POST /auth/confirm` (clé de service) avant de délivrer le JWT. Blocage après 2 refus (5 min, puis plus), voyants LED via l'ESP8266 (`esp8266-led/`), page d'habilitations `/admin`. Lancement, variables et contrat d'API complet : [`README-face.md`](README-face.md). Côté site et `auth` : [`doc/AUTH-FRONTEND.md`](../doc/AUTH-FRONTEND.md).

## assistant

- Ollama + LangChain, index vectoriel local sur `doc/`. Modèle ≤ 8B (`OLLAMA_MODEL`, ~3B par défaut).
- **Lecture seule** : aucun accès à Docker, à Ansible ni à `remediation`. Il aide à comprendre, il ne répare pas.
- Hors du chemin critique : il ne doit jamais retarder ni bloquer la boucle.
