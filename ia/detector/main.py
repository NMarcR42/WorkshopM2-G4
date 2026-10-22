"""Detecteur d'anomalies (Isolation Forest + enveloppe de securite).

Lit 4 indicateurs dans Prometheus toutes les 5 s, calcule une note 0..1.
Note >= SEUIL pendant FENETRES_REQUISES mesures consecutives = incident.
Un seul signal par incident est envoye au service de remediation (JSON simple sur /v1/anomalies).
Le detecteur ne repare rien lui-meme.
"""
import json
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
import requests
from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest

# ---------- Reglages (variables d'environnement) ----------
MODEL_PATH = os.getenv("MODEL_PATH", "models/iforest.joblib")
CALIBRATION_PATH = os.getenv("CALIBRATION_PATH", "models/calibration.json")
PERIODE_S = float(os.getenv("PERIODE_S", "5"))
FENETRES_REQUISES = int(os.getenv("FENETRES_REQUISES", "3"))
FENETRE_S = int(os.getenv("FENETRE_S", "15"))
SEUIL = float(os.getenv("SEUIL", "0.8"))
TARGET_SERVICE = os.getenv("TARGET_SERVICE", "api")
MODEL_VERSION = os.getenv("MODEL_VERSION", "iforest-enveloppe-v2")
SOURCE_MESURES = os.getenv("SOURCE_MESURES", "prometheus")  # "prometheus" ou "fictives"
PROM_URL = os.getenv("PROM_URL", "http://192.168.1.142:9090").rstrip("/")

# Envoi vers la remediation (jamais de secret dans le code !)
REMEDIATION_URL = os.getenv("REMEDIATION_URL", "").rstrip("/")  # ex. http://192.168.1.151:8080
ENGINE_TOKEN = os.getenv("ENGINE_TOKEN", "")                    # jeton Bearer du webhook
REMEDIATION_FORMAT = os.getenv("REMEDIATION_FORMAT", "simple")  # "simple" (/v1/anomalies) ou "alertmanager" (/api/v1/alerts)
REMEDIATION_ACTION = os.getenv("REMEDIATION_ACTION", "restart") # restart, isolate (sans IP) ; block_ip ou auto exigent CLIENT_IP
REMEDIATION_SERVICE = os.getenv("REMEDIATION_SERVICE", "") or TARGET_SERVICE  # service vise par la remediation
SCENARIO = os.getenv("SCENARIO", "dos")                         # utilise si action = auto
CLIENT_IP = os.getenv("CLIENT_IP", "")                          # requis par block_ip / scenario dos
ALLOW_SIM_SEND = os.getenv("ALLOW_SIM_SEND", "0") == "1"        # 1 = l'attaque simulee envoie VRAIMENT

scaler, modele, colonnes = joblib.load(MODEL_PATH)
with open(CALIBRATION_PATH, encoding="utf-8") as f:
    CALIB = json.load(f)

REQUETES = {
    "rps": 'sum(rate(nginx_http_requests_total{job="api-gateway"}[15s]))',
    "p95_ms": 'max(max_over_time(probe_duration_seconds{service="api"}[15s])) * 1000',
    "err_5xx_ratio": '1 - avg(avg_over_time(probe_success{service="api"}[15s]))',
    "cpu_pct": '100 * sum(rate(container_cpu_usage_seconds_total{name="ra-api"}[1m]))',
}

# ---------- Metriques exposees a Prometheus ----------
G_SCORE = Gauge("ra_anomaly_score", "Note d'anomalie 0..1", ["service"])
G_FLAG = Gauge("ra_anomaly_flag", "1 si note >= seuil", ["service"])
G_CONSEC = Gauge("ra_anomaly_consecutive_windows", "Mesures anormales consecutives", ["service"])

etat = {
    "attaque_simulee": False,
    "anomaly_score": 0.0,
    "anomaly_flag": 0,
    "consecutive_windows": 0,
    "signal_a_envoyer": False,
    "signal_envoye": False,
    "dernier_envoi": "jamais",
    "derniere_erreur": "aucune",
    "features": {},
    "anomaly_id": None,
}


# ---------- Mesures ----------
def mesures_fictives(attaque):
    r = np.random
    if attaque:
        return {"rps": r.normal(300, 50), "p95_ms": r.normal(2300, 500),
                "err_5xx_ratio": float(np.clip(r.normal(0.3, 0.1), 0, 1)),
                "cpu_pct": r.normal(95, 5)}
    return {"rps": max(0.0, r.normal(5, 2)), "p95_ms": max(0.0, r.normal(16, 4)),
            "err_5xx_ratio": 0.0, "cpu_pct": max(0.0, r.normal(0.3, 0.1))}


def mesures_reelles():
    m = {}
    for nom, requete in REQUETES.items():
        rep = requests.get(f"{PROM_URL}/api/v1/query", params={"query": requete}, timeout=5)
        rep.raise_for_status()
        resultat = rep.json()["data"]["result"]
        if not resultat:
            raise ValueError(f"aucune donnee pour {nom}")
        valeur = float(resultat[0]["value"][1])
        if np.isnan(valeur):
            raise ValueError(f"aucune donnee pour {nom}")
        m[nom] = valeur
    m["err_5xx_ratio"] = float(np.clip(m["err_5xx_ratio"], 0, 1))
    return m


def obtenir_mesures():
    if etat["attaque_simulee"]:
        return mesures_fictives(True)
    if SOURCE_MESURES == "prometheus":
        return mesures_reelles()
    return mesures_fictives(False)


# ---------- Note d'anomalie (deux etages) ----------
def calculer_score(m):
    x = pd.DataFrame([[m[c] for c in colonnes]], columns=colonnes)
    brut = float(np.clip(-modele.score_samples(scaler.transform(x))[0], 0, 1))
    lo, hi = CALIB["lo"], CALIB["hi"]
    s_if = brut * 0.6 / lo if brut <= lo else 0.6 + 0.3 * (brut - lo) / (hi - lo)
    s_env = 0.0
    for c in colonnes:
        e = CALIB["enveloppe"][c]
        z = (m[c] - e["med"]) / e["spread"]
        s_env = max(s_env, 0.5 * z if z <= 1 else 0.5 + 0.3 * (z - 1))
    return float(min(1.0, max(0.0, s_if, s_env)))


# ---------- Envoi a la remediation ----------
def url_alertes():
    chemin = "/api/v1/alerts" if REMEDIATION_FORMAT == "alertmanager" else "/v1/anomalies"
    if REMEDIATION_URL.endswith(chemin):
        return REMEDIATION_URL
    return REMEDIATION_URL + chemin


def construire_simple(score):
    """Format simple du service de remediation : service, remediation, score (+ client_ip)."""
    corps = {"service": REMEDIATION_SERVICE, "remediation": REMEDIATION_ACTION, "score": round(score, 2)}
    if REMEDIATION_ACTION == "auto":
        corps["scenario"] = SCENARIO
    if CLIENT_IP:
        corps["client_ip"] = CLIENT_IP
    return corps


def construire_alerte(score, m, anomaly_id):
    labels = {
        "alertname": "AnomalieDetecteeML",
        "remediation": REMEDIATION_ACTION,
        "service": REMEDIATION_SERVICE,
        "scenario": SCENARIO,
    }
    if CLIENT_IP:
        labels["client_ip"] = CLIENT_IP
    debut = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "version": "4",
        "status": "firing",
        "receiver": "ml-detector",
        "alerts": [{
            "status": "firing",
            "labels": labels,
            "annotations": {
                "summary": f"score ML {score:.2f}",
                "description": json.dumps({k: round(v, 3) for k, v in m.items()}),
                "detector": MODEL_VERSION,
                "anomaly_id": anomaly_id,
            },
            "startsAt": debut,
        }],
    }


def envoyer_anomalie(score, m, anomaly_id):
    if not REMEDIATION_URL or not ENGINE_TOKEN:
        etat["dernier_envoi"] = "desactive (REMEDIATION_URL ou ENGINE_TOKEN vide)"
        return False
    if etat["attaque_simulee"] and not ALLOW_SIM_SEND:
        etat["dernier_envoi"] = "bloque : attaque simulee (ALLOW_SIM_SEND=1 pour envoyer vraiment)"
        return False
    try:
        rep = requests.post(
            url_alertes(),
            json=(construire_alerte(score, m, anomaly_id) if REMEDIATION_FORMAT == "alertmanager" else construire_simple(score)),
            headers={"Authorization": f"Bearer {ENGINE_TOKEN}"},
            timeout=5,
        )
        etat["dernier_envoi"] = f"{datetime.now(timezone.utc).isoformat()} -> HTTP {rep.status_code}"
        return rep.ok
    except requests.RequestException as e:
        etat["dernier_envoi"] = f"echec : {type(e).__name__}"
        return False


# ---------- Boucle de detection ----------
def boucle():
    while True:
        try:
            m = obtenir_mesures()
            score = calculer_score(m)
            flag = int(score >= SEUIL)
            etat["consecutive_windows"] = etat["consecutive_windows"] + 1 if flag else 0
            if not flag:
                etat["anomaly_id"] = None
                etat["signal_envoye"] = False
            etat["anomaly_score"] = round(score, 3)
            etat["anomaly_flag"] = flag
            etat["features"] = {k: round(v, 3) for k, v in m.items()}
            etat["signal_a_envoyer"] = etat["consecutive_windows"] >= FENETRES_REQUISES
            if etat["signal_a_envoyer"] and not etat["signal_envoye"]:
                if etat["anomaly_id"] is None:
                    etat["anomaly_id"] = str(uuid.uuid4())
                etat["signal_envoye"] = envoyer_anomalie(score, m, etat["anomaly_id"])
            G_SCORE.labels(TARGET_SERVICE).set(score)
            G_FLAG.labels(TARGET_SERVICE).set(flag)
            G_CONSEC.labels(TARGET_SERVICE).set(etat["consecutive_windows"])
            etat["derniere_erreur"] = "aucune"
        except Exception as e:  # on garde les valeurs precedentes et on le dit
            etat["derniere_erreur"] = f"{type(e).__name__}: {e}"
        time.sleep(PERIODE_S)


@asynccontextmanager
async def lifespan(app):
    threading.Thread(target=boucle, daemon=True).start()
    yield


app = FastAPI(title="Detecteur d'anomalies", lifespan=lifespan)


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
def health():
    return {"status": "ok", "model_version": MODEL_VERSION}


@app.get("/status")
def status():
    return {
        "service": TARGET_SERVICE,
        "source_mesures": SOURCE_MESURES,
        "seuil": SEUIL,
        "attaque_simulee": etat["attaque_simulee"],
        "anomaly_score": etat["anomaly_score"],
        "anomaly_flag": etat["anomaly_flag"],
        "consecutive_windows": etat["consecutive_windows"],
        "signal_a_envoyer": etat["signal_a_envoyer"],
        "signal_envoye": etat["signal_envoye"],
        "dernier_envoi": etat["dernier_envoi"],
        "derniere_erreur": etat["derniere_erreur"],
        "features": etat["features"],
    }


# --- Simulation d'attaque (demo) : DESACTIVEE par defaut ---
# Pour la demo : lancer le conteneur avec -e ALLOW_SIM=1 (sinon ces routes repondent 404).
ALLOW_SIM = os.getenv("ALLOW_SIM", "0") == "1"

if ALLOW_SIM:
    @app.get("/simulate/attack/on")
    def attaque_on():
        etat["attaque_simulee"] = True
        return {"attaque_simulee": True}

    @app.get("/simulate/attack/off")
    def attaque_off():
        etat["attaque_simulee"] = False
        return {"attaque_simulee": False}
    