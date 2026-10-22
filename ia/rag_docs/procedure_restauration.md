# Procédure de restauration

## Principe
La remédiation choisit une action dans une liste fermée. Seul l'exécuteur change selon le mode de déploiement.

## Les trois actions
- block_source : bloque les adresses IP suspectes dans le waf pendant une durée limitée.
- restart_service : redémarre le service visé (api, auth ou frontend).
- rollback_service : revient à la version précédente du service. En mode local, c'est un simple redémarrage : limite assumée.

## Les deux modes
- Mode local (par défaut) : docker-proxy, qui n'autorise que restart, stop et kill.
- Mode ssh : playbooks Ansible lancés vers chaque machine.

## Escalade
Si la vérification échoue après une action, remediation escalade : redémarrage, puis rollback. Chaque action écrit un fichier de preuve dans /var/lib/resilience/incidents/ sur la machine ops, et les événements sont journalisés dans Loki.

## Vérification finale
Le service est rétabli seulement si POST /verify de canary réussit : transaction complète via le waf, puis contrôle du registre.

## Base de données
La sauvegarde et la restauration de la base sont décrites dans le document PCA/PRA de l'équipe.

## Après une compromission ou une fuite de données
Restaurer la disponibilité ne suffit pas. Une autre réponse est nécessaire : confinement et analyse des journaux. Elle n'est pas automatique.