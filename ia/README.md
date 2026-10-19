# ia

`detector` (ML) et `assistant` (RAG). Rôle de chacun : [Services](../doc/ARCHITECTURE.md#services). Avancement : [roadmap](../doc/ROADMAP.md).

## detector

- Isolation Forest sur des fenêtres de 10 s (req/s, latence p95, taux de 5xx, CPU), lues dans Prometheus.
- **Pas de seuil codé en dur** : le modèle est entraîné sur du trafic normal généré par nos soins ; le seuil de décision vient de la distribution des scores d'entraînement.
- Sortie : le signal d'anomalie de l'interface (a) ([ARCHITECTURE](../doc/ARCHITECTURE.md#interface-a--signal-danomalie-detector--remediation)). L'IP suspecte vient de Loki, pas du modèle.
- À documenter pour le dossier : données utilisées, préparation, modèle retenu, résultats, limites (faux positifs).
- Le modèle entraîné est **versionné dans le dépôt** (démo reproductible) ; les données brutes volumineuses sont ignorées (`ia/detector/data/raw/`).

## assistant

- Ollama + LangChain, index vectoriel local sur `doc/`. Modèle ≤ 8B (`OLLAMA_MODEL`, ~3B par défaut).
- **Lecture seule** : aucun accès à Docker, à Ansible ni à `remediation`. Il aide à comprendre, il ne répare pas.
- Hors du chemin critique : il ne doit jamais retarder ni bloquer la boucle.
