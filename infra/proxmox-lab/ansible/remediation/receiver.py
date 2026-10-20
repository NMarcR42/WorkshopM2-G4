#!/usr/bin/env python3
"""
Récepteur de remédiation — version minimale d'infra (stand-in).
Le DEV le remplacera par son propre moteur ; le contrat reste le même :
  - écoute POST /api/v1/alerts (format webhook Alertmanager v4)
  - exige Authorization: Bearer <alert_webhook_token>
  - pour chaque alerte "firing" portant un label remediation (!= none),
    lance le playbook Ansible correspondant, puis vérifie le service.
Journalise tout sur stdout -> Loki (service=remediation) et visible dans Grafana.
"""
import json, os, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = "/work"                      # dépôt ansible monté en lecture seule
TOKEN_FILE = "/run/secrets/alert_webhook_token"
COOLDOWN = 90                       # anti-rebond : même action pas relancée avant 90 s

with open(TOKEN_FILE) as f:
    TOKEN = f.read().strip()

_last = {}                          # (action,cible) -> timestamp du dernier lancement
_lock = threading.Lock()


def log(**kv):
    kv["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    print(json.dumps(kv), flush=True)


def playbook_for(labels):
    """Traduit les labels d'alerte en (playbook, extra-vars)."""
    rem = labels.get("remediation", "none")
    service = labels.get("service", "")
    client_ip = labels.get("client_ip", "")
    scenario = labels.get("scenario", "")

    if rem == "auto":               # décision confiée au moteur selon le scénario ML
        rem = {"dos": "block_ip", "injection": "restart",
               "exfiltration": "isolate"}.get(scenario, "restart")

    if rem == "restart":
        return "restart.yml", {"service": service or "api"}, service or "api"
    if rem == "recreate":
        return "recreate.yml", {"service": service or "api"}, service or "api"
    if rem == "isolate":
        return "isolate.yml", {"service": service or "api"}, service or "api"
    if rem == "block_ip" and client_ip:
        return "block_ip.yml", {"ip": client_ip}, client_ip
    if rem == "restore_db":
        return "restore_db.yml", {}, "db"
    if rem == "rollback_vm":
        return "rollback_vm.yml", {}, "vm-app"
    return None, None, None


def run(playbook, extra, cible, alertname):
    key = (playbook, cible)
    with _lock:
        if time.time() - _last.get(key, 0) < COOLDOWN:
            log(event="ignore_cooldown", alert=alertname, playbook=playbook, cible=cible)
            return
        _last[key] = time.time()

    cmd = ["ansible-playbook", f"remediation/{playbook}"]
    for k, v in extra.items():
        cmd += ["-e", f"{k}={v}"]
    log(event="remediation_start", alert=alertname, playbook=playbook, cible=cible)
    t0 = time.time()
    p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    ok = p.returncode == 0 and "SERVICE RÉTABLI" in p.stdout
    log(event="remediation_done", alert=alertname, playbook=playbook, cible=cible,
        rc=p.returncode, retabli=ok, duree_s=round(time.time() - t0, 1),
        resume=(p.stdout or p.stderr).splitlines()[-1][:200] if (p.stdout or p.stderr) else "")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body=b"ok"):
        self.send_response(code); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):      # pas de log d'accès HTTP par défaut
        pass

    def do_GET(self):
        if self.path == "/healthz":
            self._send(200, b"ok\n")
        else:
            self._send(404)

    def do_POST(self):
        if self.path != "/api/v1/alerts":
            return self._send(404)
        auth = self.headers.get("Authorization", "")
        if auth != f"Bearer {TOKEN}":
            log(event="refus_auth", remote=self.client_address[0])
            return self._send(401)
        n = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400)
        self._send(200)
        for alert in payload.get("alerts", []):
            if alert.get("status") != "firing":
                continue
            labels = alert.get("labels", {})
            name = labels.get("alertname", "?")
            pb, extra, cible = playbook_for(labels)
            if not pb:
                log(event="aucune_action", alert=name, remediation=labels.get("remediation"))
                continue
            threading.Thread(target=run, args=(pb, extra, cible, name), daemon=True).start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    log(event="demarrage", port=port)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
