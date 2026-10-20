"""Metriques Prometheus + logs JSON (consommes par le detecteur ML et par le SIEM leger)."""
import json
import logging
import sys
import time

from fastapi import FastAPI, Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response

REQUESTS = Counter("http_requests_total", "Requetes HTTP", ["method", "route", "status"])
LATENCY = Histogram(
    "http_request_duration_seconds",
    "Latence HTTP",
    ["route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
IN_FLIGHT = Gauge("http_requests_in_flight", "Requetes en cours")
TRANSACTIONS = Counter("payment_transactions_total", "Transactions traitees", ["status"])

log = logging.getLogger("api")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"), "level": record.levelname,
                   "service": "api", "msg": record.getMessage()}
        payload.update(getattr(record, "extra_fields", {}))
        return json.dumps(payload)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def client_ip(request: Request) -> str:
    # L'API n'est joignable que par le WAF : X-Forwarded-For (pose par le WAF) donne l'IP reelle.
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "-")


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def observe(request: Request, call_next):
        start = time.perf_counter()
        IN_FLIGHT.inc()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            IN_FLIGHT.dec()
            elapsed = time.perf_counter() - start
            route = getattr(request.scope.get("route"), "path", "unmatched")  # gabarit : evite l'explosion de cardinalite
            REQUESTS.labels(request.method, route, str(status)).inc()
            LATENCY.labels(route).observe(elapsed)
            if route not in ("/metrics", "/health", "/api/health"):
                log.info("request", extra={"extra_fields": {
                    "method": request.method, "path": request.url.path, "route": route,
                    "status": status, "duration_ms": round(elapsed * 1000, 1),
                    "client_ip": client_ip(request)}})

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
