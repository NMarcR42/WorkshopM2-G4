# Runbook : saturation de l'API de paiement

## Symptômes
- Le nombre de requêtes par seconde sur l'api explose.
- La latence p95 dépasse largement la normale.
- Le taux d'erreurs 5xx augmente.
- Le CPU du conteneur api est très élevé.
- La métrique payment_probe_success (sonde canary) tombe à 0.
- Le détecteur envoie un signal d'anomalie avec un score élevé.

## Diagnostic
1. Ouvrir Grafana et regarder le débit, la latence, les erreurs 5xx et payment_probe_success.
2. Dans Grafana, onglet Explore, source Loki : filtrer les logs du waf et de l'api pour trouver les sources du flux.
3. Consulter les événements de remediation dans Loki pour suivre l'incident.

## Réponse automatique
1. Le detector calcule un score toutes les 5 secondes sur une fenêtre de 10 secondes. Après plusieurs fenêtres anormales de suite, il envoie le signal à remediation.
2. remediation authentifie le signal, évite les doublons et choisit une action dans une liste fermée.
3. block_source : l'adresse IP source est bloquée dans le waf.
4. restart_service : l'api est redémarrée si elle n'est pas saine.
5. canary lance POST /verify : une transaction complète passe par le waf, puis le registre est contrôlé.
6. Succès : l'incident passe à RESOLVED. Échec : escalade (redémarrage, puis rollback).

Un simple redémarrage ne suffit pas tant que la source de l'attaque n'est pas bloquée.

## Vérification
Seul POST /verify de canary prouve la reprise. Un code retour OK d'une action signifie seulement que l'action a été appliquée, pas que le service est rétabli.

## Ce que l'opérateur ne doit pas faire
- Ne pas intervenir à la main pendant la démonstration.
- Ne pas exposer d'interface d'administration vers l'extérieur.