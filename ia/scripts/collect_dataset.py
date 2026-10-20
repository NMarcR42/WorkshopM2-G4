"""Collecte les 4 variables du contrat depuis Prometheus vers un CSV."""
import argparse
import os
import sys
import time

import pandas as pd
import requests

PROM = os.environ.get("PROM_URL", "http://192.168.1.142:9090")
STEP = "5s"
FENETRE = "15s"   # doit contenir au moins 3 mesures (scrape_interval 5s)

# A ADAPTER quand le dev a confirme les noms (labels service/status, histogramme).
REQUETES = {
    "rps": f'sum(rate(http_requests_total{{service="api"}}[{FENETRE}]))',
    "p95_ms": (
        "1000 * histogram_quantile(0.95, sum by (le) "
        f'(rate(http_request_duration_seconds_bucket{{service="api"}}[{FENETRE}])))'
    ),
    "err_5xx_ratio": (
        f'(sum(rate(http_requests_total{{service="api",status=~"5.."}}[{FENETRE}])) or vector(0))'
        f' / clamp_min(sum(rate(http_requests_total{{service="api"}}[{FENETRE}])), 0.001)'
    ),
    # Verifie : conteneur ra-api, en % d'un coeur.
    "cpu_pct": f'100 * sum(rate(container_cpu_usage_seconds_total{{name="ra-api"}}[{FENETRE}]))',
}
ORDRE = ["rps", "p95_ms", "err_5xx_ratio", "cpu_pct"]


def interroger(nom, requete, debut, fin):
    r = requests.get(
        f"{PROM}/api/v1/query_range",
        params={"query": requete, "start": debut, "end": fin, "step": STEP},
        timeout=60,
    )
    r.raise_for_status()
    resultat = r.json()["data"]["result"]
    if not resultat:
        sys.exit(f"Aucune donnee pour '{nom}'. Verifie le nom des metriques / labels.")
    valeurs = resultat[0]["values"]
    return pd.Series([float(v) for _, v in valeurs], index=[t for t, _ in valeurs])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=int, default=60, help="duree a exporter")
    p.add_argument("--out", default="data/normal.csv")
    a = p.parse_args()

    fin = time.time()
    debut = fin - a.minutes * 60
    colonnes = {n: interroger(n, q, debut, fin) for n, q in REQUETES.items()}

    df = pd.DataFrame(colonnes)[ORDRE]
    df = df.replace([float("inf"), float("-inf")], pd.NA).ffill().fillna(0)

    df.to_csv(a.out, index=False)
    print(f"{len(df)} lignes ecrites dans {a.out}")
    print(df.describe().round(3))


if __name__ == "__main__":
    main()
    