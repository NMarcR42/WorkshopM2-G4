"""Logs JSON (collectés par Promtail : c'est l'audit des actions) et métriques Prometheus."""
import json
import logging
import sys

from prometheus_client import Counter, Gauge, Histogram

INCIDENTS = Counter("remediation_incidents_total", "Incidents terminés", ["status"])
ACTIONS = Counter("remediation_actions_total", "Actions exécutées", ["action", "result"])
ACTIVE = Gauge("remediation_incidents_active", "Incidents en cours de traitement")
RECOVERY = Histogram(
    "remediation_recovery_seconds",
    "Du signal à la reprise vérifiée",
    buckets=(5, 10, 20, 30, 45, 60, 90, 120, 300),
)

log = logging.getLogger("remediation")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"), "level": record.levelname,
                   "service": "remediation", "msg": record.getMessage()}
        payload.update(getattr(record, "extra_fields", {}))
        return json.dumps(payload, default=str)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def event(msg: str, level: int = logging.INFO, **fields) -> None:
    log.log(level, msg, extra={"extra_fields": fields})
