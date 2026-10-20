"""Entrée du moteur : webhook Alertmanager v4 (contrat infra) et demande de remédiation qu'on en déduit."""
from typing import Literal

from pydantic import BaseModel, Field

Action = Literal["restart", "recreate", "isolate", "block_ip", "restore_db", "rollback_vm"]


class Alert(BaseModel):
    # Alertmanager ajoute des champs (generatorURL, endsAt…) : on les ignore, seuls status et labels comptent.
    status: str = ""
    labels: dict[str, str] = {}
    annotations: dict[str, str] = {}
    fingerprint: str = ""
    startsAt: str = ""


class Webhook(BaseModel):
    alerts: list[Alert] = Field(default=[], max_length=100)


class RemediationRequest(BaseModel):
    """Une alerte traduite en action. Rien de libre : action en liste fermée, service validé, IP validée."""
    anomaly_id: str = Field(min_length=1, max_length=64)   # rend l'appel idempotent (Alertmanager répète les alertes)
    alertname: str
    scenario: str = ""
    action: Action
    auto: bool = False             # la décision d'action vient du moteur (remediation=auto), pas de l'alerte
    target: str                    # clé d'anti-rebond : service, IP, « db » ou « vm-app »
    service: str                   # service visé, ou à redémarrer si l'action n'en désigne pas (block_ip)
    ip: str | None = None

    def as_signal(self) -> dict:
        """Forme stockée dans l'incident, lue par le dashboard (score, suspects) : le format ne change pas."""
        suspects = [{"kind": "ip", "value": self.ip, "share": 1.0}] if self.ip else []
        return {"alertname": self.alertname, "scenario": self.scenario, "action": self.action, "target": self.target,
                "anomaly_id": self.anomaly_id, "target_service": self.service, "score": None, "suspects": suspects}
