# Métriques pour le pilier IA — détecteur d'anomalies

Comment l'IA récupère les données, quelles features utiliser, et comment reboucler vers la remédiation.
Les métriques sont **réellement alimentées** : un générateur de trafic de fond (`ra-loadgen` sur vm-ops)
produit en continu un trafic légitime qui respire entre ~1 et ~6 requêtes/s. Le modèle apprend donc
une base « normale » ; pendant l'attaque, l'anomalie se détache de cette base.

## 1. Où lire les données (depuis vm-ia)

| Source | Endpoint | Pour quoi |
|---|---|---|
| Prometheus | `http://192.168.1.142:9090/api/v1/query` et `/query_range` | métriques (CPU, réseau, latence, erreurs) |
| Loki | `http://192.168.1.142:3100/loki/api/v1/query_range` | journaux (WAF, auth, système) |

**Chaîne de logs vérifiée le 19/10 depuis vm-ia (192.168.1.152)** :
- Loki répond (`/ready` = 200) et les **5 VM défensives** y envoient leurs logs (label `host`).
- Labels exploitables : `host`, `job` (`docker`/`journal`), `service`, `container`, `unit`, `level`, `syslog_identifier`.
- Le WAF produit ~7000 lignes / 10 min ; une attaque de test a bien fait remonter 6 lignes
  `ModSecurity: Access denied` avec l'IP source — le signal de sécurité est lisible par l'IA.
- vm-attack (Windows, attaquant) et vm-siem ne sont **pas** dans ce flux : la première est hors
  périmètre, la seconde est le SIEM du pilier Cyber (Graylog), source parallèle. Exemple d'extraction d'historique pour l'entraînement :

```python
import requests, time
PROM = "http://192.168.1.142:9090"
def series(q, minutes=180, step=30):
    end = int(time.time()); start = end - minutes*60
    r = requests.get(f"{PROM}/api/v1/query_range",
                     params={"query": q, "start": start, "end": end, "step": step})
    return r.json()["data"]["result"]
```

## 2. Features recommandées (toutes alimentées aujourd'hui)

| Feature | Requête PromQL | Signal d'attaque |
|---|---|---|
| Débit de requêtes | `sum(rate(container_network_receive_packets_total{name="ra-waf"}[1m]))` | pic = DoS / scan |
| Latence applicative | `probe_duration_seconds{service=~"api|auth|frontend"}` | hausse = saturation |
| Disponibilité | `probe_success{job=~"blackbox-http|synthetic"}` | 0 = service KO |
| CPU par conteneur | `rate(container_cpu_usage_seconds_total{name=~"ra-.*"}[1m])` | pic anormal |
| Mémoire conteneur | `container_memory_working_set_bytes{name=~"ra-.*"}` | fuite / abus |
| Réseau conteneur | `rate(container_network_receive_bytes_total{name=~"ra-.*"}[1m])` | exfiltration / flood |
| Connexions PostgreSQL | `pg_stat_activity_count` | pic = abus applicatif |
| CPU / mémoire hôte | `node_cpu_seconds_total`, `node_memory_MemAvailable_bytes` | saturation VM |

Côté journaux (Loki, pour des features textuelles ou un comptage) :

```logql
# requêtes bloquées par le WAF, par IP source, sur 1 min
sum by (client_ip) (count_over_time({service="waf"} |= "ModSecurity: Access denied"
  | regexp `\[client (?P<client_ip>[0-9.]+)\]` [1m]))
```

## 3. Ce que l'IA doit exposer (contrat de sortie)

Le détecteur publie un endpoint **`GET http://192.168.1.152:8500/metrics`** (format Prometheus) avec :

```
# HELP ra_anomaly_score Score d'anomalie (0 = normal, 1 = très anormal)
# TYPE ra_anomaly_score gauge
ra_anomaly_score{service="api",scenario="dos"} 0.07
ra_anomaly_score{service="api",scenario="injection"} 0.02
```

Prometheus le collecte déjà (cible `ml-detector`, aujourd'hui en échec car l'endpoint n'existe pas encore).
Dès qu'il répond, la règle d'alerte `AnomalieDetecteeML` se déclenche automatiquement au-dessus de **0.8**
pendant 15 s, et part vers le moteur de remédiation avec `remediation=auto`. Le label `scenario` permet
au moteur de choisir l'action (`dos`→block_ip, `injection`→restart, `exfiltration`→isolate).

Le dashboard Grafana a déjà un panneau « Score d'anomalie ML (seuil 0.8) » prêt à l'afficher.

### Deux chemins pour déclencher la remédiation depuis l'IA

Le moteur (`vm-ops:8080`) ne comprend **qu'un seul format : le webhook Alertmanager v4** (objet avec
`alerts[]`, chaque alerte portant `status` et `labels`), avec `Authorization: Bearer <alert_webhook_token>`.

- **Chemin recommandé — via la métrique** : l'IA expose seulement `ra_anomaly_score`. Prometheus détecte,
  Alertmanager met en forme et poste au moteur. **Aucun payload ni jeton à gérer côté IA**, et la
  corrélation (groupement, inhibition, anti-rebond) s'applique.
- **Chemin direct (repli) — l'IA poste elle-même** sur `vm-ops:8080`. Elle doit alors produire le format
  Alertmanager et porter le jeton. Payload minimal **testé** :

```json
{ "alerts": [ { "status": "firing", "labels": {
  "alertname": "AnomalieDetecteeML", "remediation": "auto",
  "scenario": "dos", "service": "api", "client_ip": "203.0.113.200" } } ] }
```

Labels requis selon l'action : `restart`/`recreate`/`isolate` → `service` (défaut `api`) ;
`block_ip` → `client_ip` ; `restore_db`/`rollback_vm` → aucun ; `auto` → `scenario`
(+ `client_ip` si `dos`).

## 4. Pistes de modèle (au choix de l'IA)

- **Isolation Forest** ou **One-Class SVM** sur un vecteur de features normalisées (débit, latence, CPU, réseau), ré-entraîné périodiquement sur la fenêtre « normale ».
- **Seuils adaptatifs** type `z-score` glissant sur chaque métrique (baseline mobile + écart-type).
- La base d'apprentissage « normale » est fournie en continu par `ra-loadgen` ; coupez-le si vous voulez
  un trafic strictement maîtrisé (`loadgen_enabled: false` dans `main.yml`, puis `site.yml --limit ops`).

## 5. Ollama (assistant opérateur, séparé du détecteur)

- API : `http://192.168.1.152:11434` (modèles ≤ 8 milliards de paramètres, déclarés dans `ollama_models`).
- Corpus RAG : le dossier `docs/` (procédures, architecture, PCA/PRA). L'assistant reste **en lecture seule**.
