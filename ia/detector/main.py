import os
import time
import threading

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI
from prometheus_client import Gauge, make_asgi_app

# Réglages (modifiables sans toucher au code)
MODEL_PATH = os.getenv("MODEL_PATH", "models/iforest.joblib")
PERIODE_S = int(os.getenv("PERIODE_S", "5"))                 # un calcul toutes les 5 s
FENETRES_REQUISES = int(os.getenv("FENETRES_REQUISES", "3"))  # fenêtres anormales de suite

scaler, modele, colonnes = joblib.load(MODEL_PATH)

# Valeurs publiées pour Grafana / Prometheus
score_gauge = Gauge("anomaly_score", "Score d'anomalie entre 0 et 1 (plus haut = plus anormal)")
flag_gauge = Gauge("anomaly_flag", "1 si la fenêtre est anormale, 0 sinon")
consec_gauge = Gauge("anomaly_consecutive_windows", "Fenêtres anormales de suite")

# État courant + interrupteur de simulation (TEMPORAIRE, pour tester sans plateforme)
etat = {"attaque": False, "score": 0.0, "flag": 0, "consecutive": 0, "mesure": {}}
rng = np.random.default_rng()


def mesures_fictives():
    """Fabrique une fenêtre de métriques inventées (normal ou attaque)."""
    if etat["attaque"]:
        v = {"rps": rng.normal(300, 50), "p95_ms": rng.normal(2300, 500),
             "err_5xx_ratio": rng.normal(0.3, 0.1), "cpu_pct": rng.normal(95, 5)}
    else:
        v = {"rps": rng.normal(20, 5), "p95_ms": rng.normal(80, 20),
             "err_5xx_ratio": rng.normal(0.005, 0.005), "cpu_pct": rng.normal(30, 10)}
    v["rps"] = max(0.0, v["rps"])
    v["p95_ms"] = max(10.0, v["p95_ms"])
    v["err_5xx_ratio"] = min(1.0, max(0.0, v["err_5xx_ratio"]))
    v["cpu_pct"] = min(100.0, max(0.0, v["cpu_pct"]))
    return v


def boucle():
    """Toutes les PERIODE_S secondes : lit une fenêtre, calcule le score, le publie."""
    while True:
        mesure = mesures_fictives()
        x = scaler.transform(pd.DataFrame([[mesure[c] for c in colonnes]], columns=colonnes))
        score = float(min(1.0, max(0.0, -modele.score_samples(x)[0])))
        flag = 1 if modele.predict(x)[0] == -1 else 0
        etat["consecutive"] = etat["consecutive"] + 1 if flag else 0
        score_gauge.set(score)
        flag_gauge.set(flag)
        consec_gauge.set(etat["consecutive"])
        etat["score"], etat["flag"], etat["mesure"] = score, flag, mesure
        time.sleep(PERIODE_S)


app = FastAPI()
app.mount("/metrics", make_asgi_app())
threading.Thread(target=boucle, daemon=True).start()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/status")
def status():
    return {
        "attaque_simulee": etat["attaque"],
        "anomaly_score": round(etat["score"], 3),
        "anomaly_flag": etat["flag"],
        "consecutive_windows": etat["consecutive"],
        "signal_a_envoyer": etat["consecutive"] >= FENETRES_REQUISES,
    }


@app.get("/simulate/attack/on")
def attaque_on():
    etat["attaque"] = True
    return {"attaque_simulee": True}


@app.get("/simulate/attack/off")
def attaque_off():
    etat["attaque"] = False
    return {"attaque_simulee": False}