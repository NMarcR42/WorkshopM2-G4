# CLAUDE.md

Workshop EPSI BAC+5 de 4 jours (POC, pas de prod) : **PROJECT RESILIENCE-ALPHA**. Le sujet est dans `doc/*.pdf`, mais son essentiel est résumé dans les documents ci-dessous : ne pas le relire.

## Lire d'abord

1. [`doc/ARCHITECTURE.md`](doc/ARCHITECTURE.md) — architecture, contrats (a) et (b), modes de déploiement, sécurité.
2. [`doc/STACK.md`](doc/STACK.md) — contraintes imposées et rôle de chaque outil.
3. [`doc/ROADMAP.md`](doc/ROADMAP.md) — état d'avancement, priorités, calendrier.

## Règle d'or

Une seule boucle autonome : attaque → détection ML → décision → remédiation → **vérification métier** (transaction rejouée via `canary`). Elle doit tourner en **mono-hôte** depuis un clone frais. Toute décision se juge à : « est-ce que cela fiabilise la boucle ? » Pas de bonus avant que le cœur passe (voir la roadmap).

## Règles de travail

- Ne pas modifier les interfaces (a) et (b) de `ARCHITECTURE.md` sans prévenir les autres domaines.
- Le code métier ne dépend jamais du mode de déploiement : tout passe par variables d'environnement.
- Secrets : via `secrets:` du compose (`/run/secrets/…`), jamais en variable d'environnement ni dans git ; jamais de secret dans un prompt.
- Chaque service Python : `Dockerfile`, `/health`, `/metrics`, logs JSON sur stdout, tests ; `dev/api` sert de modèle (conventions dans [`dev/README.md`](dev/README.md)).
- Un dossier de service n'est créé que s'il contient du code. Une information vit dans **un seul** document : mettre à jour la source, pas les copies.
- Git : branches `dev` / `ia` / `infra` / `cyber`, PR vers `main` obligatoire — voir [`doc/GITHUB.md`](doc/GITHUB.md).
- Données 100 % fictives ; actions offensives limitées à notre SI.
