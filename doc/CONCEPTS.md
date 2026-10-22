# Concepts

Glossaire pour les membres qui ne sont pas du domaine concerné : une phrase par notion. Le détail est dans [ARCHITECTURE](ARCHITECTURE.md), l'usage des outils dans [STACK](STACK.md).

## Résilience

| Terme | Dans notre projet |
|---|---|
| **Boucle autonome** | Attaque → détection → décision → remédiation → vérification, sans humain. Un humain qui intervient pendant la démo = 0/5 sur l'axe remédiation. |
| **Zero-Touch Recovery** | Nom du sujet pour la reprise sans intervention : c'est la boucle autonome. |
| **Vérification métier** | Rejouer une vraie transaction fictive avec succès. Un conteneur « Up » ne prouve rien. |
| **Canary** | Faux client qui paie toutes les 5 s via le WAF ; sa réussite ou son échec donne l'état du service (avant / pendant / après). |
| **Contrôle de cohérence** (`ledger/check`) | Vérifie que chaque solde = solde initial + crédits − débits ; détecte des données incohérentes après incident. |
| **Incident** | Une anomalie prise en charge par `remediation`, de `OPEN` à `RESOLVED` (ou escalade). Journalisé. |
| **RTO / RPO** | Durée maximale de coupure acceptée / quantité maximale de données perdues acceptée. Objectifs chiffrés dans le PCA/PRA. |
| **Chaos engineering** | Provoquer volontairement des pannes (jeudi) pour vérifier que la reprise tient. |
| **Idempotent** | Rejouer deux fois une action (ou une requête avec la même `Idempotency-Key`) donne le même résultat. Indispensable pour une reprise fiable. |

## Remédiation

| Terme | Dans notre projet |
|---|---|
| **Action** | Une opération de la liste fermée de `remediation` : `restart`, `recreate`, `block_ip`, `isolate`, `restore_db`, `rollback_vm`. |
| **Executor** | La façon d'exécuter une action. Mode `ansible` (déploiement sur VM) : playbooks Ansible vers les machines. Mode `local` (mono-hôte, dev et secours) : appels au `docker-proxy`. L'interface de `remediation` est identique. |
| **docker-proxy** | Mode mono-hôte uniquement : filtre devant le socket Docker, `remediation` peut redémarrer des conteneurs, rien d'autre. |
| **Alerte** | Déclencheur de la remédiation : webhook Alertmanager (v4) vers `remediation`, avec le label `remediation=<action>`. Le détecteur publie un score ; Alertmanager lève l'alerte. |
| **Liste fermée** | `remediation` n'exécute que des actions prévues ; rien de ce qui arrive dans le signal n'est passé au shell. |

## Déploiement

| Terme | Dans notre projet |
|---|---|
| **Mono-hôte** | Tout sur une machine (`ROLES=all`) : mode de dev et de secours. |
| **Multi-machines** | Déploiement sur VM (`vm-app`, `vm-obs`, `vm-ops`, `vm-ia`, `vm-siem`, `vm-sauv`), voir [`archi_infra.png`](archi_infra.png). |
| **Rôle** (`ROLES`) | Ce que fait une machine ; choisit les fichiers compose à lancer. |
| **Cloisonnement** | Séparer les composants (réseaux, machines, secrets) pour limiter ce qu'une compromission peut atteindre. |
| **Runner self-hosted** | Agent GitHub installé sur une VM, qui exécute le déploiement (la VM n'est pas joignable depuis les runners GitHub). |

## IA

| Terme | Dans notre projet |
|---|---|
| **Fenêtre / features** | Le temps est découpé en tranches de 10 s ; on calcule req/s, latence p95, taux de 5xx, CPU. Le modèle note chaque tranche. |
| **Isolation Forest** | Modèle non supervisé appris sur du trafic **normal** : il isole ce qui s'en écarte. Pas de seuil codé en dur, le seuil vient de la distribution des scores d'entraînement. |
| **Faux positif** | Alerte déclenchée sur un trafic normal ; limitée en exigeant N fenêtres anormales consécutives. |
| **RAG** | L'assistant retrouve des passages de nos documents avant de répondre, avec un petit modèle local (≤ 8B). Il conseille, il ne répare pas. |

## Sécurité

| Terme | Dans notre projet |
|---|---|
| **WAF** | Pare-feu applicatif devant l'API (BunkerWeb : ModSecurity + OWASP CRS, limitation de débit, bannissement automatique) ; sert aussi à **bloquer l'IP attaquante**. |
| **SIEM** | Les événements de sécurité (403 du WAF, échecs de login, actions de remédiation) : logs centralisés dans Loki (règles d'alerte) et corrélation dans le SIEM Graylog (`vm-siem`), voir [`archi_infra.png`](archi_infra.png). |
| **JWT** | Jeton signé émis par `auth`, vérifié localement par l'API (une panne d'`auth` ne bloque pas les paiements). |
| **Secret** | Tout mot de passe, token ou clé : jamais dans git, jamais collé à une IA. Voir [`cyber/README.md`](../cyber/README.md). |

## Gouvernance

| Terme | Dans notre projet |
|---|---|
| **EBIOS RM** | Méthode d'analyse de risques : ce qu'on protège, contre quoi, avec quels scénarios. |
| **PCA / PRA** | Plan de continuité / de reprise d'activité, adaptés à la plateforme livrée. |
| **NIS2 / DORA** | Réglementations européennes de cybersécurité et de résilience financière ; on distingue ce qu'un prototype peut démontrer de ce qu'il ne peut pas. |
