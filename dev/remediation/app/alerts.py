"""Traduit les labels d'une alerte Alertmanager en demande de remédiation (même table que receiver.py de l'infra)."""
import ipaddress

from .config import Settings
from .schemas import Alert, RemediationRequest

# remediation=auto : le moteur choisit selon le scénario annoncé par le détecteur ML.
AUTO_BY_SCENARIO = {"dos": "block_ip", "injection": "restart", "exfiltration": "isolate"}
SERVICE_ACTIONS = ("restart", "recreate", "isolate", "block_ip")
# Actions qui ne visent pas un service du compose : la cible est fixe.
FIXED_TARGET = {"restore_db": ("db", "db"), "rollback_vm": ("vm-app", "vm-app")}


def build_request(alert: Alert, s: Settings) -> tuple[RemediationRequest | None, str]:
    """Renvoie (demande, raison). demande=None : alerte ignorée, la raison est journalisée."""
    labels = alert.labels
    action = labels.get("remediation", "none")
    auto = action == "auto"
    if auto:
        action = AUTO_BY_SCENARIO.get(labels.get("scenario", ""), "restart")

    name = labels.get("alertname", "?")
    anomaly_id = (f"{alert.fingerprint or name}-{alert.startsAt}")[:64]
    common = {"anomaly_id": anomaly_id, "alertname": name, "scenario": labels.get("scenario", ""), "auto": auto}

    if action in FIXED_TARGET:
        target, service = FIXED_TARGET[action]
        return RemediationRequest(action=action, target=target, service=service, **common), "ok"
    if action not in SERVICE_ACTIONS:
        return None, "aucune_action"

    service = labels.get("service") or "api"
    # Le label vient d'une alerte, donc d'une source qu'un attaquant peut influencer indirectement : liste fermée.
    if service not in s.allowed_services:
        return None, "service_hors_liste"

    if action != "block_ip":
        return RemediationRequest(action=action, target=service, service=service, **common), "ok"

    raw_ip = labels.get("client_ip", "")
    if not raw_ip:
        return None, "client_ip_manquant"
    try:
        ip = ipaddress.ip_address(raw_ip)
    except ValueError:
        return None, "ip_invalide"
    # Jamais bloquer nos propres réseaux (canary, boucle locale) : on couperait notre preuve de reprise.
    if any(ip in net for net in s.protected_cidrs):
        return None, "reseau_protege"
    return RemediationRequest(action=action, target=str(ip), service=service, ip=str(ip), **common), "ok"
