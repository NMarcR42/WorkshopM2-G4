from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from . import db, observability
from .routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    observability.setup_logging()
    db.open_pool()
    yield
    db.close_pool()


app = FastAPI(title="Payments API (fictive)", version="0.1.0", lifespan=lifespan)
observability.install(app)
app.include_router(router)


@app.exception_handler(psycopg.OperationalError)
@app.exception_handler(PoolTimeout)
def db_unavailable(request: Request, exc: Exception):
    # Degradation propre : le client (et le canary) voit un 503, pas une stack trace.
    return JSONResponse({"detail": "Base de donnees indisponible"}, status_code=503, headers={"Retry-After": "2"})


@app.get("/health", include_in_schema=False)
def health():
    """Liveness : le process repond. Ne dit RIEN du metier (voir /ready et le canary)."""
    return {"status": "ok"}


@app.get("/ready", include_in_schema=False)
def ready():
    """Readiness : la base repond."""
    if not db.ping():
        return JSONResponse({"status": "db_unavailable"}, status_code=503)
    return {"status": "ready"}
