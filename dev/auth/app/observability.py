"""Métriques Prometheus + logs JSON. Les échecs de login alimentent le SIEM léger (Loki)."""
import json
import logging
import sys
import time

from fastapi import FastAPI, Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response

REQUESTS = Counter("http_requests_total", "Requetes HTTP", ["method", "route", "status"])
LATENCY = Histogram(
    "http_request_duration_seconds",
    "Latence HTTP",
    ["route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
LOGINS = Counter("auth_logins_total", "Tentatives de connexion", ["result"])

log = logging.getLogger("auth")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"), "level": record.levelname,
                   "service": "auth", "msg": record.getMessage()}
        payload.update(getattr(record, "extra_fields", {}))
        return json.dumps(payload)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def client_ip(request: Request) -> str:
    # Seul le WAF atteint ce service : X-Forwarded-For (posé par le WAF) donne l'IP réelle du client.
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "-")


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def observe(request: Request, call_next):
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            elapsed = time.perf_counter() - start
            route = getattr(request.scope.get("route"), "path", "unmatched")  # gabarit : évite l'explosion de cardinalité
            REQUESTS.labels(request.method, route, str(status)).inc()
            LATENCY.labels(route).observe(elapsed)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
