"""Interface (b) : exécution d'une action. Deux executors, même contrat, choisis par REMEDIATION_MODE.

Rien du signal n'atteint un shell : les noms de service viennent d'une liste fermée (Literal du schéma),
les IP sont validées en amont, les commandes sont des listes d'arguments (jamais une chaîne passée à un shell).
"""
import json
import os
import subprocess
from pathlib import Path

import httpx

from .config import Settings
from .journal import now


class ActionError(Exception):
    pass


class LocalExecutor:
    """Mode mono-hôte : docker-proxy (restart uniquement) + liste de blocage dans un volume partagé avec le WAF."""

    def __init__(self, s: Settings):
        self.s = s
        # DOCKER_HOST est au format tcp://hôte:port ; le proxy parle HTTP.
        self.base = s.docker_host.replace("tcp://", "http://", 1)

    def run(self, action: str, incident_id: str, params: dict) -> dict:
        if action == "block_source":
            return self._block(params["block_ips"])
        if action in ("restart_service", "rollback_service"):
            # Pas de retour de version en local (limite assumée, voir ARCHITECTURE) : le rollback est un redémarrage.
            return self._restart(params["target_service"])
        raise ActionError(f"action inconnue: {action}")

    def _block(self, ips: list[str]) -> dict:
        path = Path(self.s.blocklist_file)
        content = "".join(f"{ip}\n" for ip in sorted(ips))
        # Le WAF relit son fichier au redémarrage : écrire la liste COMPLÈTE rend l'action idempotente.
        changed = not path.exists() or path.read_text() != content
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(content)
        os.replace(tmp, path)
        if changed:
            self._restart(self.s.waf_service)
        return {"changed": changed, "ips": sorted(ips)}

    def _restart(self, service: str) -> dict:
        name = self.s.container_template.format(service=service)
        try:
            r = httpx.post(f"{self.base}/containers/{name}/restart", params={"t": 10}, timeout=self.s.action_timeout_s)
        except httpx.HTTPError as exc:
            raise ActionError(f"docker-proxy injoignable ({type(exc).__name__})") from exc
        if r.status_code != 204:
            raise ActionError(f"redémarrage de {name} refusé ou échoué (HTTP {r.status_code})")
        return {"changed": True, "container": name}


class SshExecutor:
    """Mode multi-machines : un playbook Ansible par action (infra/ansible/playbooks/<action>.yml)."""

    def __init__(self, s: Settings):
        self.s = s

    def run(self, action: str, incident_id: str, params: dict) -> dict:
        if not self.s.ansible_inventory:
            raise ActionError("ANSIBLE_INVENTORY non défini")
        cmd = [
            "ansible-playbook", "-i", self.s.ansible_inventory,
            str(Path(self.s.ansible_playbooks) / f"{action}.yml"),
            "-e", json.dumps({"incident_id": incident_id, **params}),
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=self.s.action_timeout_s, check=False)
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise ActionError(f"ansible-playbook: {type(exc).__name__}") from exc
        if r.returncode != 0:
            raise ActionError(f"ansible-playbook code {r.returncode}: {(r.stdout + r.stderr)[-300:]}")
        return {"changed": True}


def make_executor(s: Settings):
    if s.mode == "ssh":
        return SshExecutor(s)
    if s.mode == "local":
        return LocalExecutor(s)
    raise RuntimeError(f"REMEDIATION_MODE inconnu: {s.mode}")


def run_and_record(executor, journal, incident_id: str, action: str, params: dict) -> dict:
    """Exécute l'action et écrit <action>.json (changed, started_at, ended_at). Lève ActionError en cas d'échec."""
    record = {"action": action, "params": params, "started_at": now()}
    try:
        record.update(executor.run(action, incident_id, params), result="ok")
        return record
    except ActionError as exc:
        record.update(result="error", error=str(exc))
        raise
    finally:
        record["ended_at"] = now()
        journal.write_action(incident_id, action, record)
