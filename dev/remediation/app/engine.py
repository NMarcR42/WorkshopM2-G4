"""Cerveau de la remédiation : exécute l'action demandée par l'alerte, escalade si besoin, ne conclut qu'avec la preuve du canary.

Principe : une action qui « réussit » ne prouve rien (le code retour dit que la commande est passée, pas que le
service marche). Seul POST /verify du canary — un vrai paiement via le WAF — clôt l'incident.
"""
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import observability as obs
from .config import Settings
from .executors import ActionError, run_and_record
from .journal import Journal
from .schemas import RemediationRequest

# Escalade si l'action demandée ne suffit pas (du moins au plus intrusif). rollback_vm n'y figure pas : trop destructeur
# pour être déclenché sans qu'une alerte le demande explicitement.
ESCALATION = {"block_ip": ("restart", "recreate"), "restart": ("recreate",)}


class Engine:
    def __init__(self, s: Settings, journal: Journal, executor):
        self.s = s
        self.journal = journal
        self.executor = executor
        self.lock = threading.Lock()
        # IP bloquées -> date d'expiration. Persisté : un redémarrage du moteur ne doit pas débloquer l'attaquant.
        self._blocks_path = Path(s.incidents_dir) / "blocks.json"
        self.blocks: dict[str, float] = self._load_blocks()
        self._last: dict[tuple[str, str], float] = {}  # (action, cible) -> instant du dernier lancement (anti-rebond)

    # ---------- entrée (webhook Alertmanager, voir alerts.py) ----------

    def submit(self, req: RemediationRequest) -> tuple[dict | None, bool]:
        """Renvoie (incident, nouveau?). Dédoublonne : Alertmanager répète l'alerte pendant la réparation."""
        with self.lock:
            same = self.journal.by_anomaly(req.anomaly_id)
            if same:
                return same, False
            active = self.journal.active()
            if active:
                return active, False
            last = next(iter(self.journal.recent(1)), None)
            if last and last["status"] == "RESOLVED" and self._age_s(last["ended_at"]) < self.s.cooldown_s:
                return last, False
            key = (req.action, req.target)
            stamp = self._last.get(key)
            if stamp is not None and time.monotonic() - stamp < self.s.action_cooldown_s:
                obs.event("ignore_cooldown", alert=req.alertname, action=req.action, target=req.target)
                return last, False
            self._last[key] = time.monotonic()
            inc = self.journal.create(req.as_signal())
            obs.ACTIVE.inc()
        obs.event("incident_opened", incident_id=inc["id"], alert=req.alertname, action=req.action, target=req.target)
        threading.Thread(target=self._handle, args=(inc, req), daemon=True).start()
        return inc, True

    # ---------- traitement ----------

    def _handle(self, inc: dict, req: RemediationRequest) -> None:
        started = time.monotonic()
        status, by = "UNRESOLVED", None
        try:
            status, by = self._remediate(inc, req)
        except Exception as exc:  # un bug du moteur ne doit jamais laisser un incident « en cours » à vie
            self.journal.add(inc, "engine_error", detail=type(exc).__name__)
            obs.event("engine_error", logging.ERROR, incident_id=inc["id"], error=repr(exc))
        finally:
            self.journal.finish(inc, status, by)
            obs.ACTIVE.dec()
            obs.INCIDENTS.labels(status).inc()
            if status == "RESOLVED":
                obs.RECOVERY.observe(time.monotonic() - started)
            obs.event("incident_closed", incident_id=inc["id"], status=status, resolved_by=by,
                      duration_s=round(time.monotonic() - started, 1))

    def _remediate(self, inc: dict, req: RemediationRequest) -> tuple[str, str | None]:
        # Garde anti faux positif : décision « auto » du ML, rien à bloquer et service sain -> on ne touche à rien.
        if req.auto and req.action != "block_ip" and self.s.auto_verify_first:
            ok, res = self._verify(inc)
            # Une vérification déléguée au playbook ne dit rien de l'état AVANT action : elle ne peut pas écarter l'alerte.
            if ok and not res.get("delegated"):
                return "RESOLVED", "none"

        # L'action demandée par l'alerte d'abord, puis escalade. On s'arrête dès que le canary prouve la reprise.
        plan = [(req.action, self._params(req))]
        plan += [(a, {"service": req.service}) for a in ESCALATION.get(req.action, ())]

        for action, params in plan:
            self.journal.add(inc, "action_started", action=action, params=params)
            try:
                run_and_record(self.executor, self.journal, inc["id"], action, params)
                obs.ACTIONS.labels(action, "ok").inc()
            except ActionError as exc:
                obs.ACTIONS.labels(action, "error").inc()
                self.journal.add(inc, "action_failed", action=action, error=str(exc))
                obs.event("action_failed", logging.WARNING, incident_id=inc["id"], action=action, error=str(exc))
                continue  # une action en échec ne bloque pas l'escalade
            obs.event("action_done", incident_id=inc["id"], action=action)
            if self._wait_recovery(inc):
                return "RESOLVED", action

        # Plus rien à tenter automatiquement : on le dit clairement plutôt que de boucler.
        self.journal.add(inc, "escalated", detail="liste d'actions épuisée, intervention humaine requise")
        return "UNRESOLVED", None

    def _params(self, req: RemediationRequest) -> dict:
        if req.action == "block_ip":
            return {"ip": req.ip, "block_ips": self._add_blocks([req.ip]), "block_ttl_s": self.s.block_ttl_s}
        return {"service": req.service}

    # ---------- vérification (preuve de reprise) ----------

    def _verify(self, inc: dict) -> tuple[bool, dict]:
        if not self.s.canary_url:
            # Pas de canary (VM-OPS) : la preuve métier est celle du playbook (code 0 + « SERVICE RÉTABLI », qui rejoue
            # une transaction via le WAF). Sans cela chaque incident serait escaladé à tort après une action réussie.
            result = {"ok": True, "delegated": True, "detail": "vérification métier faite par le playbook"}
            self.journal.add(inc, "verify", ok=True, detail=result["detail"])
            return True, result
        try:
            r = httpx.post(f"{self.s.canary_url}/verify", timeout=self.s.verify_timeout_s)
            result = r.json() if r.status_code == 200 else {"ok": False, "detail": f"canary HTTP {r.status_code}"}
        except (httpx.HTTPError, ValueError) as exc:
            result = {"ok": False, "detail": f"canary injoignable ({type(exc).__name__})"}
        # Sans sonde, aucune preuve : « ne sait pas » compte comme un échec.
        ok = result.get("ok") is True
        self.journal.add(inc, "verify", ok=ok, failed_step=result.get("failed_step"), detail=result.get("detail"))
        return ok, result

    def _wait_recovery(self, inc: dict) -> bool:
        deadline = time.monotonic() + self.s.verify_timeout_s
        while True:
            ok, _ = self._verify(inc)
            if ok:
                return True
            if time.monotonic() + self.s.verify_interval_s >= deadline:
                return False
            time.sleep(self.s.verify_interval_s)

    # ---------- liste de blocage ----------

    def _add_blocks(self, ips: list[str]) -> list[str]:
        with self.lock:
            expiry = time.time() + self.s.block_ttl_s
            for ip in ips:
                self.blocks[ip] = expiry
            self._save_blocks()
            return sorted(self.blocks)

    def expire_blocks(self) -> None:
        """Débloque les IP dont le TTL est passé (un faux positif ne bloque pas quelqu'un à vie)."""
        with self.lock:
            gone = [ip for ip, exp in self.blocks.items() if exp <= time.time()]
            if not gone:
                return
            for ip in gone:
                del self.blocks[ip]
            self._save_blocks()
            remaining = sorted(self.blocks)
        try:
            self.executor.unblock(gone, remaining)
            obs.event("blocks_expired", ips=gone, remaining=len(remaining))
        except ActionError as exc:
            obs.event("action_failed", logging.WARNING, action="unblock", error=str(exc), reason="expiry")

    def _load_blocks(self) -> dict[str, float]:
        try:
            return {k: float(v) for k, v in json.loads(self._blocks_path.read_text()).items()}
        except (OSError, ValueError):
            return {}

    def _save_blocks(self) -> None:
        tmp = self._blocks_path.with_name("blocks.json.tmp")
        tmp.write_text(json.dumps(self.blocks))
        tmp.replace(self._blocks_path)

    @staticmethod
    def _age_s(iso: str | None) -> float:
        if not iso:
            return float("inf")
        return (datetime.now(timezone.utc) - datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds()
