"""Vue de supervision : agrège l'état du paiement (canary), les incidents (remediation) et l'historique (Prometheus).

Lecture seule par construction : ce service n'expose que des GET et n'appelle jamais une route qui agit.
Le navigateur ne parle qu'à lui ; les adresses et le token des services de contrôle restent côté serveur.
"""
import json
import logging
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from prometheus_client.parser import text_string_to_metric_families
from starlette.responses import Response

from .config import settings

log = logging.getLogger("supervision")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"), "level": record.levelname,
                           "service": "supervision", "msg": record.getMessage()})


handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
logging.getLogger("httpx").setLevel(logging.WARNING)

app = FastAPI(title="Supervision", version="0.1.0")

# Requêtes de l'historique. Étiquette `service` : voir infra/monitoring/targets.yml.
QUERIES = {
    "probe": 'max(payment_probe_success{service="canary"})',
    "rps": 'sum(rate(http_requests_total{service="api"}[30s]))',
    "p95_ms": '1000 * histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{service="api"}[30s])))',
}


def _iso_age_s(iso: str | None) -> float | None:
    if not iso:
        return None
    then = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds()


def read_probe() -> dict:
    """État courant lu directement sur le canary (plus frais que Prometheus, qui scrute toutes les 5 s)."""
    try:
        r = httpx.get(f"{settings.canary_url}/metrics", timeout=settings.timeout_s)
        r.raise_for_status()
        values = {s.name: s.value for fam in text_string_to_metric_families(r.text) for s in fam.samples
                  if s.name.startswith("payment_probe_") and not s.labels}
    except (httpx.HTTPError, ValueError):
        return {"reachable": False}
    last = values.get("payment_probe_last_run_timestamp_seconds")
    age = round(time.time() - last, 1) if last else None
    return {
        "reachable": True,
        "ok": values.get("payment_probe_success") == 1.0,
        "age_s": age,
        "stale": age is None or age > settings.probe_stale_s,
        "duration_s": values.get("payment_probe_duration_seconds"),
    }


def read_incidents(limit: int = 10) -> list[dict] | None:
    """None = moteur injoignable (différent de « aucun incident »)."""
    try:
        r = httpx.get(f"{settings.remediation_url}/v1/incidents", params={"limit": limit},
                      headers={"Authorization": f"Bearer {settings.engine_token}"}, timeout=settings.timeout_s)
        r.raise_for_status()
        return [_summary(i) for i in r.json()]
    except (httpx.HTTPError, ValueError):
        return None


def _summary(inc: dict) -> dict:
    sig = inc.get("signal", {})
    started, ended = _iso_age_s(inc["created_at"]), _iso_age_s(inc.get("ended_at"))
    return {
        "id": inc["id"],
        "status": inc["status"],
        "target_service": inc["target_service"],
        "created_at": inc["created_at"],
        "ended_at": inc.get("ended_at"),
        "resolved_by": inc.get("resolved_by"),
        "duration_s": round(started - ended, 1) if started is not None and ended is not None else None,
        "score": sig.get("score"),
        "suspects": sig.get("suspects", []),
        "timeline": inc.get("timeline", []),
    }


def global_state(probe: dict, incidents: list[dict] | None) -> str:
    """Une seule étiquette pour le bandeau : c'est ce que le jury doit comprendre en un coup d'œil."""
    active = next((i for i in incidents or [] if i["status"] == "IN_PROGRESS"), None)
    if active:
        return "REMEDIATING"
    if not probe["reachable"] or probe["stale"]:
        return "UNKNOWN"          # sans sonde fraîche, on ne prétend pas que tout va bien
    if not probe["ok"]:
        return "DEGRADED"
    last = next(iter(incidents or []), None)
    if last and last["status"] == "RESOLVED" and (_iso_age_s(last["ended_at"]) or 1e9) < 120:
        return "RECOVERED"
    return "HEALTHY"


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/status")
def status() -> dict:
    probe, incidents = read_probe(), read_incidents()
    return {
        "state": global_state(probe, incidents),
        "probe": probe,
        "engine_reachable": incidents is not None,
        "incidents": incidents or [],
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


@app.get("/api/history")
def history(minutes: int = Query(15, ge=1, le=120)) -> dict:
    """Séries « avant / pendant / après » : état du paiement, trafic et latence de l'API."""
    end = time.time()
    out: dict = {"step_s": 5, "series": {}}
    for name, query in QUERIES.items():
        points: list[list[float]] = []
        try:
            r = httpx.get(f"{settings.prometheus_url}/api/v1/query_range", timeout=settings.timeout_s,
                          params={"query": query, "start": end - minutes * 60, "end": end, "step": 5})
            r.raise_for_status()
            result = r.json()["data"]["result"]
            for t, v in (result[0]["values"] if result else []):
                if math.isfinite(float(v)):   # NaN : pas de trafic, on laisse un trou plutôt qu'un faux zéro
                    points.append([float(t), float(v)])
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        out["series"][name] = points
    return out


# Le site compilé est servi par ce même service (une seule image, un seul port).
if Path(settings.static_dir).is_dir():
    app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="ui")
