# Plan de Continuité et de Reprise d'Activité (PCA/PRA) — PROJECT RESILIENCE-ALPHA

> Plan adapté au démonstrateur réellement livré. S'appuie sur l'[analyse EBIOS RM](EBIOS-RM.md) et
> l'[architecture](../infra/PROCEDURE-INFRA.md). Les RTO/RPO annoncés sont **mesurés sur la plateforme**,
> pas théoriques. Document de travail — pilier Gouvernance.

## 1. Objectif et principe directeur

Garantir la **continuité du service de paiement** et sa **reprise sans intervention humaine**
(Zero-Touch Recovery) face à un incident de sécurité ou une défaillance. Le principe : **détecter →
décider → agir → vérifier**, automatiquement, puis prouver que le service métier est de nouveau utilisable
(nouvelle transaction fictive réussie), et non qu'un simple conteneur a redémarré.

## 2. Services critiques et classification

| Service | Rôle | Criticité | D | I | C | T |
|---|---|---|---|---|---|---|
| API de paiement (`api`) | Traitement des transactions | **Vitale** | 4 | 4 | 3 | 3 |
| Authentification (`auth`) | Accès opérateurs | **Vitale** | 4 | 4 | 4 | 3 |
| Base de données (`postgres`) | Données de transaction | **Vitale** | 4 | 4 | 4 | 3 |
| WAF / point d'entrée (`waf`,`gateway`) | Exposition et filtrage | **Vitale** | 4 | 3 | 2 | 3 |
| Frontal web (`frontend`) | Interface | Importante | 3 | 2 | 2 | 2 |
| Observabilité / remédiation | Détection et reprise | **Vitale** (support) | 4 | 4 | 3 | 4 |
| Secrets (Vault/SOPS) | Identifiants | **Vitale** (support) | 3 | 4 | 4 | 3 |

D = Disponibilité, I = Intégrité, C = Confidentialité, T = Traçabilité (échelle 1–4).

## 3. Objectifs de continuité : RTO / RPO

| Service | RTO cible | RPO cible | Valeur **mesurée** | Moyen de reprise |
|---|---|---|---|---|
| API / Auth / Frontal | < 2 min | n/a (sans état) | **~28 s** | `restart.yml` / `recreate.yml` auto |
| Base de données (disponibilité) | < 2 min | n/a | ~28 s | `restart.yml` |
| Base de données (intégrité/corruption) | < 5 min | **5 min** | RPO réel 5 min (dump validé) | `restore_db.yml` |
| Hôte `vm-app` (compromission) | < 5 min | dernier snapshot | **~65 s** | `rollback_vm.yml` (snapshot Proxmox) |
| Blocage d'une source d'attaque | < 1 min | n/a | quelques secondes | ban BunkerWeb + `block_ip.yml` |

> RPO 5 min = perte de données maximale acceptée, alignée sur la fréquence des sauvegardes (vérifiée :
> dumps toutes les 5 min, fraîcheur ~37 s au moment du contrôle). RTO = délai de remise en service,
> vérifié par une transaction de contrôle à la fin de chaque remédiation.

## 4. Scénarios de sinistre couverts et procédures de reprise

| # | Sinistre | Déclencheur de détection | Décision | Action automatique | Responsable du plan |
|---|---|---|---|---|---|
| S1 | Service applicatif indisponible | `probe_success=0` → `ServiceIndisponible` | restart | `restart.yml` puis vérif transaction | Moteur de remédiation |
| S2 | Conteneur disparu / état corrompu | `ConteneurDisparu` (cAdvisor) | recreate | `recreate.yml` (image saine) | Moteur |
| S3 | Attaque applicative (SQLi/XSS) | WAF 403 + `AttaqueApplicativeBloqueeParWAF` | block_ip | ban BunkerWeb + `block_ip.yml` | WAF + Moteur |
| S4 | Déni de service | 429 + `RafaleDeRequetes` | block_ip | limitation débit + ban | WAF + Moteur |
| S5 | Compromission d'un conteneur | score ML / logs anormaux | isolate | `isolate.yml` (preuve + coupure + conteneur neuf) | Moteur |
| S6 | Corruption / altération des données | incohérence métier | restore_db | `restore_db.yml` (dernier dump validé) | Moteur + validation humaine conseillée |
| S7 | Compromission de l'hôte `vm-app` | anomalie système persistante | rollback_vm | `rollback_vm.yml` (snapshot `baseline-sain`) | Moteur (jeton Proxmox restreint) |

**Distinction essentielle** (exigée par le sujet) : restaurer la **disponibilité** (S1, S2) n'est pas
corriger une **compromission** ou une **fuite** (S5, S6, S7). Les réponses sont différenciées et tracées.

## 5. Choix de restauration et justification

- **Redémarrage (restart)** : le plus rapide, pour une indisponibilité sans corruption d'état.
- **Recréation (recreate)** : repart de l'**image d'origine**, pour écarter une corruption du conteneur.
- **Isolement (isolate)** : conserve les **preuves** (image + logs + inspect) avant de couper le réseau et de
  relancer un conteneur neuf — adapté à une compromission à investiguer.
- **Restauration BDD (restore_db)** : revient au dernier **dump validé** ; une validation humaine est
  recommandée pour ne pas réécrire des transactions légitimes récentes.
- **Rollback VM (rollback_vm)** : dernier recours, retour à un état système sain certifié par snapshot.

## 6. Sauvegardes — dispositif vérifié

- **Fréquence** : toutes les 5 min (minuteur systemd `ra-backup-db.timer`, actif).
- **Validité** : chaque dump est relu (`pg_restore --list`) avant d'être conservé ; un dump illisible est rejeté.
- **Rétention** : 24 h en local sur `vm-app` (288 dumps).
- **Externalisation** : copie vers `vm-sauv` en **écriture seule** (`rrsync -wo -no-del`). Test réalisé :
  depuis `vm-app`, la **suppression et la lecture** des sauvegardes distantes sont **refusées** →
  protection anti-rançongiciel effective même si `vm-app` est compromise.
- **Supervision** : métrique `ra_backup_last_success_timestamp_seconds` + alerte `SauvegardeTropAncienne`
  au-delà de 15 min.

## 7. Rôles et responsabilités

| Rôle | Responsabilité en cas d'incident |
|---|---|
| Moteur de remédiation (automatisé) | Exécute la reprise et la vérification métier |
| Pilier Infra | Maintient playbooks, sauvegardes, snapshots, observabilité |
| Pilier Cyber | SIEM (Graylog), analyse post-incident, investigation des preuves (`isolate`) |
| Pilier IA | Détection d'anomalies, assistant opérateur (RAG) |
| Pilier Gouvernance | Décisions d'arbitrage, validation d'une restauration de données, reporting |

## 8. Risques résiduels après reprise

- **Fenêtre de détection** (~10–20 s) : une attaque agit avant la réponse automatique.
- **restore_db** peut réécrire des transactions légitimes postérieures au dernier dump (jusqu'à 5 min).
- **rollback_vm** revient à un état antérieur : les transactions entre le snapshot et l'incident sont perdues
  si elles ne sont pas couvertes par une sauvegarde BDD plus récente — d'où la **complémentarité**
  sauvegarde BDD (RPO 5 min) + snapshot.
- Une **compromission persistante** non détectée par les règles/ML survivrait à un simple restart : d'où
  la différenciation des réponses et la conservation des preuves.

## 9. Lecture NIS2 / DORA (activité financière fictive)

| Exigence | Démontrable sur le prototype | Non démontrable en 4 jours |
|---|---|---|
| Gestion des risques (NIS2 art. 21 / DORA ch. II) | ✅ EBIOS RM, registre, mesures | Revue périodique, comité des risques |
| Détection et traitement des incidents | ✅ détection + réponse auto + traçabilité | Notification réglementaire sous 24/72 h |
| Continuité et tests (DORA ch. IV) | ✅ PCA/PRA, RTO/RPO mesurés, tests de reprise | Tests avancés (TLPT), scénarios multi-sites |
| Sauvegarde et restauration | ✅ dumps validés, externalisation write-only | Rétention longue, site de secours distant |
| Journalisation / traçabilité | ✅ logs centralisés, actions de reprise tracées | Conservation réglementaire pluriannuelle |
| Gestion des tiers (DORA ch. V) | ⚠️ cité (PSP, hébergeur) | Contrats, audits fournisseurs |

**Recommandation au commanditaire** : le démonstrateur prouve la **chaîne technique de résilience** et son
pilotage par les risques. Pour une mise en production, prioriser : filtrage inter-VM, PKI interne (fin du
certificat auto-signé), Vault en haute disponibilité (auto-unseal), site de sauvegarde distant, et la
procédure de **notification réglementaire** des incidents.

## 10. Au-delà du prototype (plan d'amélioration)

1. Activer le pare-feu inter-VM (matrice de flux déjà rédigée, phase 11).
2. Autorité de certification interne + TLS validé de bout en bout.
3. Vault en 5/3 Shamir ou auto-unseal (transit) et politiques d'accès par service.
4. Externalisation des sauvegardes hors hôte Proxmox (3-2-1).
5. Entraînement du modèle ML sur données représentatives + boucle de ré-entraînement.
6. Exercice de crise documenté et notification réglementaire NIS2/DORA.
