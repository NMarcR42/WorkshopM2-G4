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

# ---------- Configuration (variables d'environnement) ----------
MODEL_PATH = os.getenv("MODEL_PATH", "models/iforest.joblib")
CALIBRATION_PATH = os.getenv("CALIBRATION_PATH", "models/calibration.json")
PERIODE_S = int(os.getenv("PERIODE_S", "5"))
FENETRES_REQUISES = int(os.getenv("FENETRES_REQUISES", "3"))
FENETRE_S = int(os.getenv("FENETRE_S", "15"))
SEUIL = float(os.getenv("SEUIL", "0.8"))
TARGET_SERVICE = os.getenv("TARGET_SERVICE", "api")
MODEL_VERSION = os.getenv("MODEL_VERSION", "iforest-enveloppe-v2")

# Source des mesures : "prometheus" (reel) ou "fictif" (tests)
SOURCE_MESURES = os.getenv("SOURCE_MESURES", "prometheus")
PROM_URL = os.getenv("PROM_URL", "http://192.168.1.142:9090").rstrip("/")

# Rien de secret dans le code
REMEDIATION_URL = os.getenv("REMEDIATION_URL", "").rstrip("/")
ENGINE_TOKEN = os.getenv("ENGINE_TOKEN", "")

scaler, modele, colonnes = joblib.load(MODEL_PATH)
with open(CALIBRATION_PATH) as f:
    CALIB = json.load(f)

# Requetes Prometheus (memes que scripts/collect_dataset.py)
REQUETES = {
    "rps": 'sum(rate(nginx_http_requests_total{job="api-gateway"}[15s]))',
    "p95_ms": 'max(max_over_time(probe_duration_seconds{service="api"}[15s])) * 1000',
    "err_5xx_ratio": '1 - avg(avg_over_time(probe_success{service="api"}[15s]))',
    "cpu_pct": '100 * sum(rate(container_cpu_usage_seconds_total{name="ra-api"}[1m]))',
}

# ---------- Metriques Prometheus ----------
g_score = Gauge("ra_anomaly_score", "Score d'anomalie (0 a 1)", ["service"])
g_flag = Gauge("ra_anomaly_flag", "1 si anomalie detectee", ["service"])
g_consec = Gauge("ra_anomaly_consecutive_windows", "Fenetres anormales consecutives", ["service"])

# ---------- Etat partage ----------
etat = {
    "attaque_simulee": False,
    "score": 0.0,
    "flag": 0,
    "consecutive": 0,
    "features": {},
    "anomaly_id": None,
    "envoye": False,
    "dernier_envoi": "jamais",
    "derniere_erreur": "aucune",
}


def mesures_fictives(attaque):
    if attaque:
        return {
            "rps": max(0, np.random.normal(300, 50)),
            "p95_ms": max(0, np.random.normal(2300, 500)),
            "err_5xx_ratio": min(1, max(0, np.random.normal(0.3, 0.1))),
            "cpu_pct": min(100, max(0, np.random.normal(95, 5))),
        }
    return {
        "rps": max(0, np.random.normal(5, 2)),
        "p95_ms": max(0, np.random.normal(16, 4)),
        "err_5xx_ratio": 0.0,
        "cpu_pct": max(0, np.random.normal(0.3, 0.1)),
    }


def mesures_reelles():
    """Lit les 4 mesures dans Prometheus (une requete instantanee chacune)."""
    resultat = {}
    for nom, requete in REQUETES.items():
        r = requests.get(
            f"{PROM_URL}/api/v1/query",
            params={"query": requete},
            timeout=5,
        )
        r.raise_for_status()
        data = r.json()["data"]["result"]
        if not data:
            raise ValueError(f"aucune donnee pour {nom}")
        valeur = float(data[0]["value"][1])
        if np.isnan(valeur):
            raise ValueError(f"valeur NaN pour {nom}")
        resultat[nom] = valeur
    resultat["err_5xx_ratio"] = min(1.0, max(0.0, resultat["err_5xx_ratio"]))
    return resultat


def obtenir_mesures():
    # La simulation d'attaque (tests) a toujours la priorite
    if etat["attaque_simulee"]:
        return mesures_fictives(True)
    if SOURCE_MESURES == "prometheus":
        return mesures_reelles()
    return mesures_fictives(False)


def calculer_score(m):
    """Score final 0..1 = maximum de deux etages :
    1) Isolation Forest (combinaisons inhabituelles de mesures)
    2) Enveloppe de securite (valeur tres au-dela de la plage normale)
    """
    x = pd.DataFrame([[m[c] for c in colonnes]], columns=colonnes)
    brut = float(np.clip(-modele.score_samples(scaler.transform(x))[0], 0, 1))
    lo, hi = CALIB["lo"], CALIB["hi"]
    if brut <= lo:
        s_if = brut * 0.6 / lo
    else:
        s_if = 0.6 + 0.3 * (brut - lo) / (hi - lo)

    s_env = 0.0
    for c in colonnes:
        e = CALIB["enveloppe"][c]
        z = (m[c] - e["med"]) / e["spread"]
        s_c = 0.5 * z if z <= 1 else 0.5 + 0.3 * (z - 1)
        s_env = max(s_env, s_c)

    return float(min(1.0, max(0.0, s_if, s_env)))


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
        "suspects": [],
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
            m = obtenir_mesures()
            etat["derniere_erreur"] = "aucune"
            etat["features"] = m
            score = calculer_score(m)
            flag = 1 if score >= SEUIL else 0

            if flag:
                etat["consecutive"] += 1
            else:
                etat["consecutive"] = 0
                etat["anomaly_id"] = None
                etat["envoye"] = False

            etat["score"] = score
            etat["flag"] = flag

            g_score.labels(TARGET_SERVICE).set(score)
            g_flag.labels(TARGET_SERVICE).set(flag)
            g_consec.labels(TARGET_SERVICE).set(etat["consecutive"])

            if etat["consecutive"] >= FENETRES_REQUISES and not etat["envoye"]:
                if etat["anomaly_id"] is None:
                    etat["anomaly_id"] = str(uuid.uuid4())
                if envoyer_anomalie():
                    etat["envoye"] = True
        except Exception as e:
            etat["derniere_erreur"] = f"{type(e).__name__}: {e}"
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
        "source_mesures": SOURCE_MESURES,
        "seuil": SEUIL,
        "attaque_simulee": etat["attaque_simulee"],
        "anomaly_score": round(etat["score"], 3),
        "anomaly_flag": etat["flag"],
        "consecutive_windows": etat["consecutive"],
        "signal_a_envoyer": etat["consecutive"] >= FENETRES_REQUISES,
        "signal_envoye": etat["envoye"],
        "dernier_envoi": etat["dernier_envoi"],
        "derniere_erreur": etat["derniere_erreur"],
        "features": {k: round(float(v), 3) for k, v in etat["features"].items()},
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
