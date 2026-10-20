"""Interface (b) : exécution d'une action. Deux executors, même contrat, choisis par REMEDIATION_MODE.

Rien de l'alerte n'atteint un shell : les services viennent d'une liste fermée, les IP sont validées en amont,
les commandes sont des listes d'arguments (jamais une chaîne passée à un shell).
Les noms d'action sont ceux des playbooks de l'infra (remediation/<action>.yml).
"""
import os
import subprocess
from pathlib import Path

import httpx

from .config import Settings
from .journal import now


class ActionError(Exception):
    pass


class AnsibleExecutor:
    """Mode VM-OPS : un playbook Ansible par action, lancé depuis le dépôt ansible/ monté en lecture seule."""

    def __init__(self, s: Settings):
        self.s = s

    def run(self, action: str, incident_id: str, params: dict) -> dict:
        extra = self._extra_vars(action, params)
        return self._playbook(action, extra)

    def unblock(self, ips: list[str], remaining: list[str]) -> dict:
        """Le contrat infra ne définit que block_ip : le déblocage n'existe que si l'infra livre unblock_ip.yml."""
        if not (Path(self.s.ansible_workdir) / self.s.ansible_playbooks_subdir / "unblock_ip.yml").is_file():
            raise ActionError("unblock_ip.yml absent : déblocage à faire côté WAF (ban expiré ou ra-remediate unblock-ip)")
        for ip in ips:
            self._playbook("unblock_ip", {"ip": ip})
        return {"changed": True, "ips": ips}

    @staticmethod
    def _extra_vars(action: str, params: dict) -> dict:
        if action == "block_ip":
            return {"ip": params["ip"]}
        if action in ("restart", "recreate", "isolate"):
            return {"service": params["service"]}
        return {}  # restore_db, rollback_vm : cible fixée par le playbook

    def _playbook(self, action: str, extra: dict) -> dict:
        cmd = ["ansible-playbook"]
        if self.s.ansible_inventory:
            cmd += ["-i", self.s.ansible_inventory]
        cmd.append(f"{self.s.ansible_playbooks_subdir}/{action}.yml")
        for k, v in extra.items():
            cmd += ["-e", f"{k}={v}"]
        try:
            r = subprocess.run(cmd, cwd=self.s.ansible_workdir, capture_output=True, text=True, check=False,
                               timeout=self.s.ansible_timeout_s)
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise ActionError(f"ansible-playbook: {type(exc).__name__}") from exc
        # Le code retour seul ne suffit pas : le playbook doit aussi annoncer que le service est rétabli.
        if r.returncode != 0:
            raise ActionError(f"ansible-playbook code {r.returncode}: {(r.stdout + r.stderr)[-300:]}")
        if self.s.ansible_success_marker not in r.stdout:
            raise ActionError(f"playbook terminé sans « {self.s.ansible_success_marker} »: {r.stdout[-300:]}")
        lines = r.stdout.strip().splitlines()
        return {"changed": True, "rc": r.returncode, "resume": lines[-1][:200] if lines else ""}


class LocalExecutor:
    """Mode mono-hôte : docker-proxy (restart uniquement) + liste de blocage dans un volume partagé avec le WAF."""

    def __init__(self, s: Settings):
        self.s = s
        # DOCKER_HOST est au format tcp://hôte:port ; le proxy parle HTTP.
        self.base = s.docker_host.replace("tcp://", "http://", 1)

    def run(self, action: str, incident_id: str, params: dict) -> dict:
        if action == "block_ip":
            return self._block(params["block_ips"])
        if action in ("restart", "recreate"):
            # Pas de recréation sans socket Docker complet (limite assumée, voir ARCHITECTURE) : recreate = redémarrage.
            return self._restart(params["service"])
        # isolate, restore_db, rollback_vm : il faut Ansible et l'hyperviseur, donc rien à simuler en local.
        raise ActionError(f"action {action} indisponible en mode local")

    def unblock(self, ips: list[str], remaining: list[str]) -> dict:
        return self._block(remaining)

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


def make_executor(s: Settings):
    if s.mode in ("ansible", "ssh"):  # « ssh » : ancien nom, encore posé par infra/compose/remediation-ssh.yml
        return AnsibleExecutor(s)
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
