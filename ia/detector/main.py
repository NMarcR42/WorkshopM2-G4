import os
import json
import time
import uuid
import threading
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
import requests
from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST

# ---------- Configuration (tout vient de variables d'environnement) ----------
MODEL_PATH = os.getenv("MODEL_PATH", "models/iforest.joblib")
PERIODE_S = int(os.getenv("PERIODE_S", "5"))
FENETRES_REQUISES = int(os.getenv("FENETRES_REQUISES", "3"))
FENETRE_S = int(os.getenv("FENETRE_S", "15"))
TARGET_SERVICE = os.getenv("TARGET_SERVICE", "api")
MODEL_VERSION = os.getenv("MODEL_VERSION", "iforest-v1")

# Rien de secret dans le code : adresse et token viennent de l'environnement
REMEDIATION_URL = os.getenv("REMEDIATION_URL", "").rstrip("/")
ENGINE_TOKEN = os.getenv("ENGINE_TOKEN", "")

scaler, modele, colonnes = joblib.load(MODEL_PATH)

# ---------- Métriques Prometheus ----------
g_score = Gauge("ra_anomaly_score", "Score d'anomalie (0 a 1)", ["service"])
g_flag = Gauge("ra_anomaly_flag", "1 si anomalie detectee", ["service"])
g_consec = Gauge("ra_anomaly_consecutive_windows", "Fenetres anormales consecutives", ["service"])

# ---------- Etat partagé ----------
etat = {
    "attaque_simulee": False,
    "score": 0.0,
    "flag": 0,
    "consecutive": 0,
    "features": {},
    "anomaly_id": None,      # identifiant de l'incident en cours
    "envoye": False,         # signal deja envoye pour cet incident ?
    "dernier_envoi": "jamais",
}


def mesures_fictives():
    """TEMPORAIRE : a remplacer par la lecture de Prometheus."""
    if etat["attaque_simulee"]:
        return {
            "rps": max(0, np.random.normal(300, 50)),
            "p95_ms": max(0, np.random.normal(2300, 500)),
            "err_5xx_ratio": min(1, max(0, np.random.normal(0.3, 0.1))),
            "cpu_pct": min(100, max(0, np.random.normal(95, 5))),
        }
    return {
        "rps": max(0, np.random.normal(20, 5)),
        "p95_ms": max(0, np.random.normal(80, 20)),
        "err_5xx_ratio": min(1, max(0, np.random.normal(0.005, 0.005))),
        "cpu_pct": min(100, max(0, np.random.normal(30, 10))),
    }


def envoyer_anomalie():
    """Envoie le signal a remediation. Renvoie True si accepte."""
    if not REMEDIATION_URL or not ENGINE_TOKEN:
        etat["dernier_envoi"] = "desactive (REMEDIATION_URL ou ENGINE_TOKEN vide)"
        return False

    corps = {
        "schema_version": "1.0",
        "anomaly_id": etat["anomaly_id"],
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "detector": {"name": "isolation-forest", "model_version": MODEL_VERSION},
        "score": round(etat["score"], 4),
        "consecutive_windows": etat["consecutive"],
        "target_service": TARGET_SERVICE,
        "window_s": FENETRE_S,
        "features": {k: round(float(v), 4) for k, v in etat["features"].items()},
        "suspects": [],  # a remplir plus tard (viendra de Loki, pas du ML)
    }
    try:
        r = requests.post(
            f"{REMEDIATION_URL}/v1/anomalies",
            json=corps,
            headers={"Authorization": f"Bearer {ENGINE_TOKEN}"},
            timeout=5,
        )
        etat["dernier_envoi"] = f"HTTP {r.status_code} a {corps['detected_at']}"
        return r.status_code < 300
    except Exception as e:
        etat["dernier_envoi"] = f"echec : {type(e).__name__}"
        return False


def boucle():
    while True:
        try:
            m = mesures_fictives()
            etat["features"] = m
            x = pd.DataFrame([[m[c] for c in colonnes]], columns=colonnes)
            xs = scaler.transform(x)
            score = float(min(1.0, max(0.0, -modele.score_samples(xs)[0])))
            flag = 1 if modele.predict(xs)[0] == -1 else 0

            if flag:
                etat["consecutive"] += 1
            else:
                etat["consecutive"] = 0
                # fin d'incident : on prepare le prochain
                etat["anomaly_id"] = None
                etat["envoye"] = False

            etat["score"] = score
            etat["flag"] = flag

            g_score.labels(TARGET_SERVICE).set(score)
            g_flag.labels(TARGET_SERVICE).set(flag)
            g_consec.labels(TARGET_SERVICE).set(etat["consecutive"])

            # Signal : 3 fenetres de suite, une seule fois par incident
            if etat["consecutive"] >= FENETRES_REQUISES and not etat["envoye"]:
                if etat["anomaly_id"] is None:
                    etat["anomaly_id"] = str(uuid.uuid4())
                if envoyer_anomalie():
                    etat["envoye"] = True  # sinon on reessaie au prochain tour
        except Exception as e:
            print("Erreur dans la boucle :", e)
        time.sleep(PERIODE_S)


threading.Thread(target=boucle, daemon=True).start()

app = FastAPI(title="Detecteur d'anomalies")


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/status")
def status():
    return {
        "service": TARGET_SERVICE,
        "attaque_simulee": etat["attaque_simulee"],
        "anomaly_score": round(etat["score"], 3),
        "anomaly_flag": etat["flag"],
        "consecutive_windows": etat["consecutive"],
        "signal_a_envoyer": etat["consecutive"] >= FENETRES_REQUISES,
        "signal_envoye": etat["envoye"],
        "dernier_envoi": etat["dernier_envoi"],
    }


# ---- TEMPORAIRE : a supprimer avant le rendu final ----
@app.get("/simulate/attack/on")
def attaque_on():
    etat["attaque_simulee"] = True
    return {"attaque_simulee": True}


@app.get("/simulate/attack/off")
def attaque_off():
    etat["attaque_simulee"] = False
    return {"attaque_simulee": False}
