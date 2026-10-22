import os
import sys
import argparse
import time

import requests
import pandas as pd

PROM = os.getenv("PROM_URL", "http://192.168.1.142:9090")
STEP = 5

REQUETES = {
    "rps": 'sum(rate(nginx_http_requests_total{job="api-gateway"}[15s]))',
    "p95_ms": 'max(max_over_time(probe_duration_seconds{service="api"}[15s])) * 1000',
    "err_5xx_ratio": '1 - avg(avg_over_time(probe_success{service="api"}[15s]))',
    "cpu_pct": '100 * sum(rate(container_cpu_usage_seconds_total{name="ra-api"}[1m]))',
}
COLONNES = ["rps", "p95_ms", "err_5xx_ratio", "cpu_pct"]


def interroger(nom, requete, debut, fin):
    r = requests.get(
        f"{PROM}/api/v1/query_range",
        params={"query": requete, "start": debut, "end": fin, "step": STEP},
        timeout=60,
    )
    r.raise_for_status()
    resultat = r.json()["data"]["result"]
    if not resultat:
        print(f"Aucune donnee pour '{nom}'. Verifie le nom des metriques / labels.")
        sys.exit(1)
    valeurs = resultat[0]["values"]
    return pd.Series(
        [float(v[1]) for v in valeurs],
        index=[float(v[0]) for v in valeurs],
        name=nom,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=int, default=60)
    parser.add_argument("--out", default="data/normal.csv")
    args = parser.parse_args()

    fin = time.time()
    debut = fin - args.minutes * 60

    series = [interroger(nom, q, debut, fin) for nom, q in REQUETES.items()]
    df = pd.concat(series, axis=1)[COLONNES].dropna()
    df["err_5xx_ratio"] = df["err_5xx_ratio"].clip(0, 1)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"{len(df)} lignes ecrites dans {args.out}")
    print(df.describe())


if __name__ == "__main__":
    main()
    