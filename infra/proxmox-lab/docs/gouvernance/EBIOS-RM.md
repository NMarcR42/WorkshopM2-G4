# Analyse de risques EBIOS Risk Manager — PROJECT RESILIENCE-ALPHA

> Objet : plateforme de paiement fictive « Resilience-Alpha », démonstrateur de cyber-résilience et de
> reprise autonome. Analyse conduite selon la méthode **EBIOS RM (ANSSI)**, ancrée sur l'architecture
> réellement déployée (voir [PROCEDURE-INFRA.md](../infra/PROCEDURE-INFRA.md)) et les essais menés.
> Document de travail — pilier Gouvernance. Les valeurs de gravité/vraisemblance sont des hypothèses
> d'étude à valider avec le commanditaire fictif (Direction Nationale de la Sûreté Numérique).

## Échelles utilisées

**Gravité (G)** — impact pour l'activité :
| Niveau | Libellé | Repère pour une activité de paiement |
|---|---|---|
| G1 | Mineure | Gêne ponctuelle, aucun impact client |
| G2 | Significative | Dégradation visible, traçabilité affaiblie |
| G3 | Grave | Interruption de service, perte de confiance, données exposées |
| G4 | Critique | Arrêt prolongé du paiement, fraude, perte d'intégrité financière |

**Vraisemblance (V)** : V1 improbable · V2 possible · V3 probable · V4 très probable.
**Niveau de risque** = G × V, synthétisé en Faible / Moyen / Élevé / Critique.

---

## Atelier 1 — Cadrage et socle de sécurité

### 1.1 Périmètre et mission
Opérer une plateforme de paiement en ligne (fictive) : initier et traiter des transactions, authentifier
les opérateurs, conserver les données de transaction. Le démonstrateur doit prouver qu'un incident de
sécurité peut être **détecté et corrigé automatiquement**, sans intervention humaine.

### 1.2 Valeurs métier
| Réf | Valeur métier | Besoin DIC prioritaire |
|---|---|---|
| VM1 | Exécution d'une transaction de paiement | Disponibilité, Intégrité |
| VM2 | Authentification des opérateurs | Confidentialité, Intégrité |
| VM3 | Données de transaction (montants, comptes fictifs) | Intégrité, Confidentialité |
| VM4 | Continuité du service de paiement | Disponibilité |
| VM5 | Traçabilité des opérations et des actions de reprise | Intégrité, Traçabilité |

### 1.3 Biens supports
Hyperviseur Proxmox (nœud `pve`) ; VM `vm-app` (WAF BunkerWeb, gateway, frontend, api, auth, PostgreSQL) ;
`vm-ops` (Ansible, moteur de remédiation, Vault) ; `vm-obs` (Prometheus, Loki, Grafana, Alertmanager) ;
`vm-ia` (détection ML, assistant) ; `vm-sauv` (sauvegardes) ; réseaux Docker segmentés
(`ra_edge`, `ra_backend`, `ra_data` interne) ; secrets (SOPS+age, Vault) ; jetons (webhook, API Proxmox restreint).

### 1.4 Événements redoutés
| Réf | Événement redouté | Valeur métier | Gravité |
|---|---|---|---|
| ER1 | Indisponibilité du service de paiement | VM1, VM4 | **G4** |
| ER2 | Altération ou perte d'intégrité des données de transaction | VM3 | **G4** |
| ER3 | Fuite de données de transaction (fictives) | VM3 | G3 |
| ER4 | Compromission d'un composant et élévation de privilèges | tous | **G4** |
| ER5 | Usurpation d'identité d'un opérateur | VM2 | G3 |
| ER6 | Perte de traçabilité / effacement des journaux | VM5 | G2 |

### 1.5 Socle de sécurité et écarts
Référentiels retenus : **Guide d'hygiène ANSSI**, **CIS Docker Benchmark**, **OWASP ASVS / Top 10**,
principes **Zero-Touch Recovery**. Écarts assumés du prototype (4 jours) :
- TLS en certificat **auto-signé** (pas d'autorité interne) ;
- Vault en **descellement par clé unique** (prod : Shamir 5/3 ou auto-unseal) ;
- Services métier = **bouchons** tant que le DEV n'a pas livré ;
- Pare-feu inter-VM Proxmox **non activé** (décision d'équipe : accès ouvert pendant le workshop).

---

## Atelier 2 — Sources de risque et objectifs visés

| Réf | Source de risque (SR) | Objectif visé (OV) | Pertinence |
|---|---|---|---|
| SR1 | Cybercriminel organisé | Gain financier : fraude, exfiltration, rançongiciel | **Retenu** (motivation forte, activité financière) |
| SR2 | Hacktiviste | Déni de service, atteinte à l'image | **Retenu** (cible visible, DoS facile) |
| SR3 | Concurrent / initié malveillant | Sabotage, vol de données | Retenu (impact élevé, vraisemblance modérée) |
| SR4 | Attaquant opportuniste (script kiddie) | Défiguration, scan, exploitation de failles connues | **Retenu** (volumétrie, surface exposée) |
| SR5 | Erreur interne (non malveillante) | — | Retenu comme aléa (chaos engineering) |

Couples SR/OV prioritaires : **SR1→fraude/exfiltration**, **SR2→DoS**, **SR4→exploitation web**.

---

## Atelier 3 — Scénarios stratégiques

Écosystème (réduit au prototype) : le point d'entrée unique est le **WAF** publié via pfSense (NAT WAN→DMZ).
Les parties prenantes réelles d'une plateforme de paiement (partenaires bancaires, PSP, régulateur) sont
hors périmètre du démonstrateur mais citées pour le réalisme.

| Réf | Scénario stratégique | SR→OV | ER visé | Gravité |
|---|---|---|---|---|
| SS1 | L'attaquant atteint l'API de paiement par le point d'entrée web et exploite une faille applicative | SR1/SR4 | ER2, ER3 | G4 |
| SS2 | L'attaquant sature le point d'entrée pour rendre le paiement indisponible | SR2 | ER1 | G4 |
| SS3 | L'attaquant compromet un conteneur puis pivote vers le plan de contrôle (remédiation, Proxmox) | SR1/SR3 | ER4 | G4 |
| SS4 | L'attaquant usurpe une session d'opérateur | SR1 | ER5 | G3 |

---

## Atelier 4 — Scénarios opérationnels

Chemins d'attaque détaillés, avec la **vraisemblance** et les **mesures de détection existantes**.

### SO1 — Injection applicative (SQLi/XSS) sur l'API — SS1
Reconnaissance → envoi de requêtes malveillantes sur `/api/*` → tentative d'exfiltration de la base.
- **Vraisemblance : V3** (attaque la plus courante sur une API exposée).
- **Détecté par** : WAF BunkerWeb (ModSecurity + OWASP CRS v4, blocage 403) ; règle SIEM Loki
  `AttaqueApplicativeBloqueeParWAF` (comptage par IP) ; essai réalisé → 403 puis **bannissement automatique**.

### SO2 — Déni de service sur le point d'entrée — SS2
Flood HTTP / rafales de requêtes → saturation du WAF/gateway → indisponibilité.
- **Vraisemblance : V3**.
- **Détecté par** : limitation de débit BunkerWeb (429) + `USE_LIMIT_CONN` ; règle `RafaleDeRequetes` ;
  sonde `probe_success=0` → alerte `ServiceIndisponible`.

### SO3 — Exploitation d'un conteneur et élévation de privilèges — SS3
Exploitation d'un service → exécution de code dans un conteneur → tentative d'accès au socket Docker ou au
moteur de remédiation (privilégié).
- **Vraisemblance : V2** (nécessite une faille exploitable ; surface réduite par la segmentation).
- **Détecté par** : cAdvisor (comportement conteneur), journaux Loki, score ML (à venir). **Barrière clé** :
  le moteur de remédiation n'a **pas** le socket Docker ; il agit via une **liste blanche** `ra-remediate`
  et un compte `remediator` à sudo restreint ; réseau `ra_data` **interne** (BDD/Vault non exposés).

### SO4 — Compromission de l'hôte `vm-app` — SS3
Pivot réussi → contrôle de la VM applicative → altération des données ou persistance.
- **Vraisemblance : V2**.
- **Réponse** : retour à l'état sain par **snapshot Proxmox** (`rollback_vm.yml`, jeton API limité à la VM 200),
  mesuré à **~65 s** ; distinction nette entre restauration de disponibilité et traitement de compromission.

### SO5 — Exfiltration / fuite de données de transaction — SS1
Accès BDD → extraction de données fictives.
- **Vraisemblance : V2**.
- **Réponse** : `isolate.yml` (preuve + coupure réseau + conteneur neuf) et rotation de secrets ;
  réseau `ra_data` interne limite l'exfiltration directe.

### SO6 — Altération de l'intégrité des données — SS1
Modification non autorisée des transactions.
- **Vraisemblance : V2**.
- **Réponse** : `restore_db.yml` depuis le dernier dump **validé** (RPO 5 min), copie en **écriture seule**
  sur `vm-sauv` (protection anti-rançongiciel).

---

## Atelier 5 — Traitement du risque

### 5.1 Registre des risques et décisions
| Risque | ER | G | V | Niveau | Décision | Mesures (ancrées dans l'architecture) |
|---|---|---|---|---|---|---|
| R1 Injection applicative | ER2/ER3 | G4 | V3 | **Critique** | Réduire | WAF CRS v4, bannissement auto, SIEM, `block_ip` |
| R2 Déni de service | ER1 | G4 | V3 | **Critique** | Réduire | Limitation débit/conn, `block_ip`, détection+restart |
| R3 Compromission conteneur / élévation | ER4 | G4 | V2 | Élevé | Réduire | Moindre privilège remédiation, segmentation, no-new-privileges, `isolate` |
| R4 Compromission hôte | ER4 | G4 | V2 | Élevé | Réduire | Snapshot/rollback Proxmox, jeton API restreint |
| R5 Exfiltration de données | ER3 | G3 | V2 | Moyen | Réduire | Réseau `ra_data` interne, Vault/SOPS, `isolate`+rotation |
| R6 Altération des données | ER2 | G4 | V2 | Élevé | Réduire | Sauvegardes validées RPO 5 min, écriture seule, `restore_db` |
| R7 Usurpation d'opérateur | ER5 | G3 | V2 | Moyen | Réduire (DEV) | Auth JWT, durcissement (dépend de la livraison DEV) |
| R8 Perte de traçabilité | ER6 | G2 | V2 | Faible | Réduire | Logs centralisés Loki, journal remédiation, écriture seule |

### 5.2 Mesures transверsales (défense en profondeur)
- **Prévention** : segmentation réseau (edge/backend/data interne), moindre privilège, secrets chiffrés
  (SOPS+age, Vault), durcissement SSH, IPv6 coupé, jeton Proxmox à portée minimale.
- **Détection** : Prometheus (métriques, 5 s), blackbox (sonde + transaction fictive), Loki/SIEM (règles
  sur logs WAF, SSH, remédiation), détection ML (en cours), SIEM Graylog (pilier Cyber).
- **Réponse autonome** : Alertmanager → moteur de remédiation → playbooks Ansible → **vérification métier**.
  Reprise mesurée : **~28 s** (redémarrage service), **~65 s** (rollback VM), RPO **5 min**.
- **Gouvernance** : analyse EBIOS, PCA/PRA ([PCA-PRA.md](PCA-PRA.md)), journalisation des actions de reprise.

### 5.3 Risque résiduel
Après traitement, les risques critiques (R1, R2) sont ramenés à un niveau **Moyen** : l'attaque est bloquée
et la source bannie automatiquement, le service reste disponible. Subsistent :
- une **fenêtre de détection** (~10–20 s) pendant laquelle une attaque agit avant la réponse ;
- la dépendance au **certificat auto-signé** et à l'**absence de filtrage inter-VM** (écarts assumés) ;
- les risques liés aux **services métier non encore livrés** (R7 notamment) ;
- un **faux négatif ML** possible tant que le modèle n'est pas entraîné sur des données représentatives.

Ces risques résiduels sont **acceptés** dans le cadre du prototype et documentés comme axes d'amélioration
pour un passage en production (voir PCA/PRA §« au-delà du prototype »).
