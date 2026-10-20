import hmac
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from . import observability
from .alerts import build_request
from .config import settings
from .engine import Engine
from .executors import make_executor
from .journal import Journal
from .schemas import Webhook

engine: Engine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    observability.setup_logging()
    settings.alert_token  # échoue au démarrage si le secret manque, plutôt qu'à la première alerte
    engine = Engine(settings, Journal(settings.incidents_dir), make_executor(settings))
    stop = threading.Event()

    def expiry_loop():
        while not stop.wait(10):
            engine.expire_blocks()

    threading.Thread(target=expiry_loop, daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="Remediation", version="0.1.0", lifespan=lifespan)


def _bearer(expected: str, authorization: str | None) -> bool:
    # compare_digest : temps constant, pas d'indice sur le token par la durée de réponse.
    return bool(authorization) and hmac.compare_digest(authorization.encode(), f"Bearer {expected}".encode())


def require_alert_token(request: Request, authorization: str | None = Header(None)) -> None:
    """Seul Alertmanager (jeton de l'infra) peut déclencher une remédiation."""
    if not _bearer(settings.alert_token, authorization):
        observability.event("refus_auth", logging.WARNING, remote=request.client.host if request.client else "?")
        raise HTTPException(401, "Token invalide")


def require_token(authorization: str | None = Header(None)) -> None:
    """Lecture des incidents (dashboard)."""
    if not _bearer(settings.engine_token, authorization):
        raise HTTPException(401, "Token invalide")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mode": settings.mode}


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def process_alerts(webhook: Webhook) -> None:
    """Hors de la requête : Alertmanager attend un 200 rapide, la réparation prend des secondes."""
    for alert in webhook.alerts:
        if alert.status != "firing":
            continue
        req, reason = build_request(alert, settings)
        if req is None:
            observability.event("alerte_ignoree", alert=alert.labels.get("alertname", "?"), reason=reason,
                                remediation=alert.labels.get("remediation"))
            continue
        inc, created = engine.submit(req)
        if not created:
            observability.event("alerte_dedoublonnee", alert=req.alertname, incident_id=inc["id"] if inc else None)


@app.post("/api/v1/alerts", dependencies=[Depends(require_alert_token)])
def receive_alerts(webhook: Webhook, background: BackgroundTasks) -> dict:
    """Webhook Alertmanager v4 (contrat infra). 200 tout de suite ; l'état se lit via /v1/incidents."""
    background.add_task(process_alerts, webhook)
    return {"status": "ok"}


@app.get("/v1/incidents", dependencies=[Depends(require_token)])
def list_incidents(limit: int = Query(20, ge=1, le=200)) -> list[dict]:
    return engine.journal.recent(limit)


@app.get("/v1/incidents/{incident_id}", dependencies=[Depends(require_token)])
def get_incident(incident_id: str) -> dict:
    inc = engine.journal.incidents.get(incident_id)
    if not inc:
        raise HTTPException(404, "Incident inconnu")
    return inc
