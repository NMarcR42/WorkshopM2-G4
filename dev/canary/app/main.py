import json
import logging
import sys
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from starlette.responses import Response

from .config import settings
from .probe import run_probe

log = logging.getLogger("canary")

# 0 tant qu'aucune passe n'a réussi : "pas de preuve" doit se lire comme "pas sain".
PROBE_SUCCESS = Gauge("payment_probe_success", "1 = un paiement complet passe via le WAF, 0 = échec")
PROBE_DURATION = Gauge("payment_probe_duration_seconds", "Durée de la dernière passe")
PROBE_LAST = Gauge("payment_probe_last_run_timestamp_seconds", "Date de la dernière passe (détecte une sonde arrêtée)")
PROBE_RUNS = Counter("payment_probe_runs_total", "Passes jouées", ["result", "step"])

_last_ok: bool | None = None


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"), "level": record.levelname,
                   "service": "canary", "msg": record.getMessage()}
        payload.update(getattr(record, "extra_fields", {}))
        return json.dumps(payload)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx logue chaque requête : trop bavard toutes les 5 s


def probe_and_record() -> dict:
    """Joue une passe et met à jour métriques + logs. Partagé par la boucle et POST /verify."""
    global _last_ok
    result = run_probe()
    PROBE_SUCCESS.set(1 if result["ok"] else 0)
    PROBE_DURATION.set(result["duration_s"])
    PROBE_LAST.set(time.time())
    PROBE_RUNS.labels("ok" if result["ok"] else "fail", result["failed_step"] or "-").inc()
    # On ne journalise que les échecs et les changements d'état : une ligne toutes les 5 s noierait Loki.
    if not result["ok"] or _last_ok is not True:
        extra = {"extra_fields": {"event": "probe_ok" if result["ok"] else "probe_failed", **result}}
        log.log(logging.INFO if result["ok"] else logging.WARNING, result["detail"], extra=extra)
    _last_ok = result["ok"]
    return result


def _loop(stop: threading.Event) -> None:
    # wait() plutôt que sleep() : arrêt immédiat du conteneur ; la durée de la passe est déduite pour garder le rythme.
    while not stop.is_set():
        t0 = time.monotonic()
        probe_and_record()
        stop.wait(max(0.0, settings.interval_s - (time.monotonic() - t0)))


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    stop = threading.Event()
    thread = threading.Thread(target=_loop, args=(stop,), daemon=True)
    thread.start()
    yield
    stop.set()


app = FastAPI(title="Canary (sonde de paiement)", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    """Le process répond. L'état du paiement est dans /metrics et /verify, pas ici."""
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/verify")
def verify() -> dict:
    """Une passe à la demande : la preuve de reprise attendue par la remédiation.

    Toujours HTTP 200 : l'échec du paiement est un résultat (`ok: false`), pas une erreur de la sonde.
    """
    return probe_and_record()
