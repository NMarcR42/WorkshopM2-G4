# Runbook : saturation de l'API (attaque DoS)

Mots-clés : API saturée, saturation de l'API, surcharge, lenteur, erreurs 5xx, trafic anormal, attaque DoS, DDoS, déni de service, CPU élevé, sonde canary, payment_probe_success, score d'anomalie, block_source, restart_service, rollback_service.

## Quand utiliser ce runbook
Utiliser ce runbook quand l'API de paiement est saturée ou très lente, que le paiement de test échoue, ou que le détecteur signale une anomalie sur le service api.

## Symptômes
- Le CPU du conteneur api est très élevé.
- La métrique payment_probe_success (sonde canary) tombe à 0.
- Le débit de requêtes, la latence et les erreurs 5xx augmentent fortement.
- Le détecteur d'anomalies envoie un signal avec un score élevé (le seuil d'alerte du tableau de bord est 0.8).

## Diagnostic
1. Ouvrir le tableau de bord Grafana « Resilience-Alpha : Vue d'ensemble ».
2. Regarder « Disponibilité vue de l'extérieur » et « Sondes : succès / échec » pour confirmer que le paiement de test échoue.
3. Regarder « Score d'anomalie ML » : un score au-dessus de 0.8 confirme une anomalie.
4. Regarder « Requêtes vues par le WAF » : un pic de requêtes confirme une attaque par volume.
5. Dans Grafana, onglet Explore, source Loki : filtrer les logs du waf et de l'api pour identifier les sources du flux (adresses IP qui reviennent le plus souvent).
6. Regarder « WAF BunkerWeb : requêtes bloquées » pour voir ce que le pare-feu bloque déjà.

## Ce que fait le système automatiquement
La remédiation est automatique, sans intervention humaine. Le détecteur envoie le signal au service remediation, qui choisit parmi trois actions :
- block_source : bloque les adresses IP suspectes dans le WAF pendant une durée limitée (action typique pour une attaque DoS).
- restart_service : redémarre le service visé (api, auth ou frontend).
- rollback_service : revient à la version précédente du service.
Le service remediation vérifie ensuite le retour à la normale avec la sonde canary. L'opérateur ne lance aucune de ces actions : il observe et vérifie. Pour suivre l'incident, consulter le panneau « Actions de remédiation » (journal ra-remediate) ou les événements de remédiation dans Loki.

## Vérification du retour à la normale
1. payment_probe_success revient à 1.
2. Le CPU de l'api et la latence redescendent.
3. Le score d'anomalie repasse sous le seuil.
4. Le panneau « Redémarrages de conteneurs » ne montre pas de redémarrage en boucle.

## Quand escalader
- La remédiation n'a pas rétabli le service après plusieurs minutes.
- Le paiement de test échoue toujours alors que le score d'anomalie est redevenu normal.
- Une fausse alerte est suspectée : un pic de charge légitime ressemble à une attaque. Voir la FAQ opérateur.

## Limites de l'assistant
L'assistant explique cette procédure à partir de la documentation. Il n'a aucun accès au système : il ne redémarre aucun service et n'exécute aucune commande.