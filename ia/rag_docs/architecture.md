# Architecture de la plateforme RESILIENCE-ALPHA

## Objectif
Prouver qu'une plateforme de paiement fictive survit à une attaque sans intervention humaine : attaque, détection par le modèle de machine learning, décision, remédiation, puis vérification métier (une transaction rejouée avec succès). Un conteneur qui redémarre ne prouve rien.

## Services
- waf (nginx + ModSecurity) : filtre l'entrée, bloque les adresses IP désignées par la remédiation. Seul point exposé (port 8080).
- frontend (React + Tailwind) : vue paiement pour le client et vue supervision pour le jury.
- api (FastAPI) : virements fictifs.
- auth (FastAPI) : authentification, émission des jetons JWT.
- db (PostgreSQL) : comptes et transactions. Jamais exposée.
- canary (FastAPI) : rejoue une transaction fictive toutes les 5 secondes (métrique payment_probe_success) et expose POST /verify. C'est la preuve de reprise.
- remediation (FastAPI) : reçoit le signal d'anomalie, choisit l'action dans une liste fermée, l'exécute, vérifie via canary, journalise.
- detector (scikit-learn, Isolation Forest) : calcule un score sur des fenêtres de trafic et envoie le signal d'anomalie à remediation.
- assistant et ollama (LangChain + Ollama) : aident les opérateurs grâce à un RAG sur le dossier doc/. Lecture seule, ne pilote rien.
- prometheus, loki, grafana : métriques, journaux (SIEM léger) et tableaux de bord.
- promtail et cadvisor : agents de collecte.
- docker-proxy : autorise uniquement restart, stop et kill sur Docker (mode local).

## Réseaux Docker
- edge : waf, canary (entrée publique).
- app : waf, frontend, api, auth, db (métier).
- obs : prometheus, loki, grafana, agents (observabilité).
- ctrl : remediation, detector, canary, docker-proxy (contrôle, jamais exposé).
- ai : ollama, assistant (isolé, sans accès système).

## Modes de déploiement
- Mono-hôte (défaut) : tout sur un seul PC avec Docker. Mode de secours le jour J. La remédiation passe par docker-proxy.
- Multi-machines (optionnel) : machines front, back, ops et ai. La remédiation passe par Ansible en SSH.