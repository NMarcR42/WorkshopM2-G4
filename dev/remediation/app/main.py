import hmac
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import JSONResponse, Response

from . import observability
from .config import settings
from .engine import Engine
from .executors import make_executor
from .journal import Journal
from .schemas import Signal

engine: Engine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    observability.setup_logging()
    settings.engine_token  # échoue au démarrage si le secret manque, plutôt qu'au premier signal
    engine = Engine(settings, Journal(settings.incidents_dir), make_executor(settings))
    stop = threading.Event()

    def expiry_loop():
        while not stop.wait(10):
            engine.expire_blocks()

    threading.Thread(target=expiry_loop, daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="Remediation", version="0.1.0", lifespan=lifespan)


def require_token(authorization: str | None = Header(None)) -> None:
    """Seul le détecteur (token de service) peut déclencher ou lire les incidents."""
    expected = f"Bearer {settings.engine_token}"
    # compare_digest : temps constant, pas d'indice sur le token par la durée de réponse.
    if not authorization or not hmac.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(401, "Token invalide")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mode": settings.mode}


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/anomalies", status_code=202, dependencies=[Depends(require_token)])
def receive_anomaly(signal: Signal) -> JSONResponse:
    """Interface (a). 202 : le traitement est asynchrone, l'état se lit via /v1/incidents/{id}."""
    inc, created = engine.submit(signal)
    return JSONResponse({"incident_id": inc["id"], "deduplicated": not created}, status_code=202)


@app.get("/v1/incidents", dependencies=[Depends(require_token)])
def list_incidents(limit: int = Query(20, ge=1, le=200)) -> list[dict]:
    return engine.journal.recent(limit)


@app.get("/v1/incidents/{incident_id}", dependencies=[Depends(require_token)])
def get_incident(incident_id: str) -> dict:
    inc = engine.journal.incidents.get(incident_id)
    if not inc:
        raise HTTPException(404, "Incident inconnu")
    return inc
