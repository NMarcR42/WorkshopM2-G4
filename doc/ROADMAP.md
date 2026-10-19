# Roadmap

Document de pilotage de l'équipe. Architecture : [ARCHITECTURE](ARCHITECTURE.md). Règles Git : [GITHUB](GITHUB.md).

**Échéances** : lundi 19/10 kick-off · jeudi 22/10 **gel du code 17 h**, remise avant **23 h 59** · vendredi 23/10 jury (10 min : 5 de démo, 5 de questions).

## Principe de priorité

| Niveau | Contenu | Règle |
|---|---|---|
| **Cœur** | La boucle : attaque → détection → remédiation → vérification, en **mono-hôte** | Rien d'autre n'avance tant que la boucle ne passe pas. |
| **Obligatoire hors boucle** | Ce que le sujet impose mais qui ne bloque pas la démo : assistant RAG, gouvernance, livrables | À finir, sans jamais retarder le cœur. |
| **Bonus** | Multi-machines/SSH, 2ᵉ attaque, rollback réel, machine de sauvegarde | Seulement quand le cœur passe **10 fois de suite** sans intervention. |

**Définition de « fini » pour le cœur** : après `scripts/reset-demo.sh`, 10 exécutions consécutives de la boucle sans aucune intervention humaine, en mono-hôte, depuis un clone frais.
**Objectifs de reprise proposés** (à valider avec l'analyse EBIOS) : anomalie détectée ≤ 30 s après le début du flood ; service rétabli et vérifié (`/verify` OK) ≤ 90 s.

## Qui

Un responsable par domaine, à renseigner lundi (une personne peut en porter plusieurs). Les décisions d'architecture restent collectives.

| Domaine | Responsable | Dossiers |
|---|---|---|
| DEV | _à renseigner_ | `dev/` |
| INFRA | _à renseigner_ | `infra/`, `scripts/`, `.github/` |
| IA | _à renseigner_ | `ia/` |
| CYBER | _à renseigner_ | `cyber/` |
| GOUVERNANCE | _à renseigner_ | `doc/` (gouvernance, dossier, présentation) |

## Plan par jour

### Lundi — architecture et socle  *(en cours)*

- [x] Architecture, contrats (a) et (b), modes mono-hôte / multi-machines · **tous**
- [x] Composes par rôle, `compose.sh`, `init-local.sh`, CI · INFRA
- [x] `dev/api` : transactions, JWT, métriques, tests · DEV
- [x] Documentation · tous
- [ ] **Où tourne la démo ?** Valider avec le coach (VM Proxmox via WireGuard ou PC hôte Windows du sujet) · tous
- [ ] EBIOS RM : périmètre, biens essentiels, matrice de risques → validation coachs · GOUVERNANCE
- [ ] Clés age de l'équipe, protection de `main` · CYBER / INFRA
- [ ] Choix de l'attaque détaillée (endpoint ciblé, volume) · CYBER

### Mardi — production (chaque brique tourne en mono-hôte)

- DEV : `auth` ✅ (émet les JWT) · `frontend` paiement ✅ · `supervision` ✅ (vue du jury) · `canary` ✅ (probe + `/verify` avec `ledger/check` ; reste à tester derrière le vrai WAF) · `remediation` ✅ (interface (a), executor `local`, 3 actions, journal d'incident ; reste à brancher le vrai détecteur et le WAF)
- INFRA : Prometheus + Loki + Grafana provisionnés (dashboard « avant / pendant / après ») · `scripts/reset-demo.sh` · Dockerfiles intégrés au compose
- IA : générateur de trafic normal → jeu de données → Isolation Forest v1 → modèle figé · client qui envoie le signal (a)
- CYBER : WAF (CRS, `X-Forwarded-For`, liste de blocage rechargeable) · script de flood depuis le PC attaquant · règles SIEM (403 WAF, échecs de login)
- GOUVERNANCE : EBIOS RM terminé · début PCA/PRA et analyse NIS2/DORA
- *Fin de journée* : chaque brique démarre avec `./scripts/compose.sh up`.

### Mercredi — intégration (la boucle tourne de bout en bout)

- Première boucle complète en mono-hôte, puis répétée jusqu'à 10/10 (réglage des fenêtres, du nombre de fenêtres anormales, du cooldown)
- Premiers tests de restauration (l'API et la base tombent, le service revient et `/verify` passe)
- Assistant RAG branché sur `doc/`
- PCA/PRA terminé ; dossier technique : plan et premières sections
- **Décision go / no-go multi-machines (mercredi soir)** : VM prêtes *et* boucle 10/10 en mono-hôte → on tente le déploiement multi-machines (`REMEDIATION_MODE=ssh`). Sinon la démo se fait en mono-hôte, le multi-machines reste documenté comme cible.

### Jeudi — recette, chaos, rendus

- **Matin** : chaos (arrêt de la base, de l'API, du WAF, faux positif, double attaque), répétitions, correction des défauts de la boucle
- **Clip Chrono** (60 s max, sans coupe) : attaque depuis le PC attaquant → anomalie → réaction → service rétabli et vérifié
- Dossier PDF (8 à 12 pages hors annexes, contributions de chacun visibles), présentation `.pptx`
- **17 h : gel du code** · archive `Code.zip` sans aucun secret (relire avec `gitleaks`)
- **Avant 23 h 59** : dépôt des 4 fichiers sur le drive

### Vendredi — jury

Démo en direct sur nos machines. Préparer : machine déjà démarrée, `reset-demo.sh` lancé, onglets Grafana et supervision ouverts, plan B (mono-hôte) prêt. Aucune production de code.

## Livrables (noms imposés)

`Workshop2026-M2-G4-Dossier.pdf` · `Workshop2026-M2-G4-Pres.pptx` · `Workshop2026-M2-G4-VidChrono.mp4` · `Workshop2026-M2-G4-Code.zip`

## Backlog bonus (dans cet ordre)

1. Déploiement multi-machines en `REMEDIATION_MODE=ssh` (utilisateur `resilience`, pare-feu, `targets.yml`)
2. Rollback réel (images versionnées) à la place du simple redémarrage
3. 2ᵉ attaque (injection ou exfiltration de données fictives) avec une réponse adaptée : confinement et forensique, pas seulement restauration
4. Machine de sauvegarde de la base (`pg_dump` planifié) liée au PCA/PRA

## Risques suivis

| Risque | Parade |
|---|---|
| La boucle échoue en direct | `reset-demo.sh`, 10/10 exigé, escalade restart → rollback, plan B mono-hôte |
| VM pas prêtes ou lieu de démo incertain | Mono-hôte complet par défaut ; décision go/no-go mercredi |
| Faux positifs du détecteur | N fenêtres anormales consécutives, cooldown, modèle figé, test avec trafic normal |
| Fuite de secret | `.gitignore`, `gitleaks` en CI, SOPS pour le partagé |
| Gros merge tardif | PR petites et fréquentes, gel jeudi 17 h |
