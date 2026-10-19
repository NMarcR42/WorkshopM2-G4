# FAQ opérateur

## Que signifie le score d'anomalie ?
C'est un nombre entre 0 et 1 calculé par le modèle de détection (Isolation Forest). Plus il est élevé, plus la situation s'éloigne du fonctionnement normal.

## Comment le signal d'anomalie est-il déclenché ?
Toutes les 5 secondes, le detector calcule un score sur une fenêtre de 10 secondes. Après plusieurs fenêtres anormales de suite, il envoie le signal à remediation. Cela évite les fausses alertes ponctuelles.

## Le détecteur désigne-t-il l'adresse de l'attaquant ?
Non. Le modèle dit seulement si la situation est anormale. L'adresse suspecte vient d'un classement des sources dans Loki.

## Où voir les journaux ?
Dans Grafana, onglet Explore, source Loki. Filtrer par service, par exemple api ou waf.

## Comment savoir que le service est rétabli ?
Grâce à la métrique payment_probe_success dans Grafana, et surtout quand POST /verify de canary réussit.

## Le détecteur répare-t-il le problème ?
Non. Il envoie un signal. La remédiation choisit et exécute l'action.

## L'assistant peut-il redémarrer un service ?
Non. L'assistant lit les documents et explique. Il n'a aucun accès au système.

## Que faire en cas de fausse alerte ?
Regarder le score dans la durée et les logs. Une montée de charge légitime peut ressembler à une attaque. Signaler le cas à l'équipe IA.
