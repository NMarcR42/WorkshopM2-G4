import dataclasses
import ipaddress
import subprocess
import time

import pytest

from app.alerts import build_request
from app.config import settings as base_settings
from app.engine import Engine
from app.executors import ActionError, AnsibleExecutor
from app.journal import Journal
from app.schemas import Alert


def make_alert(remediation="block_ip", service="api", client_ip="192.168.137.2", scenario="", name="Test",
               status="firing"):
    labels = {"alertname": name, "remediation": remediation, "service": service, "client_ip": client_ip,
              "scenario": scenario}
    return {"status": status, "labels": {k: v for k, v in labels.items() if v}, "fingerprint": name + remediation}


def make_req(alert=None):
    s = dataclasses.replace(base_settings, protected_cidrs=(ipaddress.ip_network("172.16.0.0/12"),))
    return build_request(Alert(**(alert or make_alert())), s)


def req_of(**kw):
    req, reason = make_req(make_alert(**kw))
    assert req, reason
    return req


class FakeExecutor:
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def run(self, action, incident_id, params):
        self.calls.append(action)
        if action in self.fail:
            raise ActionError("panne simulée")
        return {"changed": True}

    def unblock(self, ips, remaining):
        self.calls.append("unblock")
        return {"changed": True}


def make_engine(tmp_path, monkeypatch, health, executor=None, **overrides):
    """health : liste de résultats successifs du canary (le dernier est répété)."""
    overrides = {"action_cooldown_s": 0, **overrides}
    s = dataclasses.replace(
        base_settings, incidents_dir=str(tmp_path), verify_timeout_s=0.3, verify_interval_s=0.05, cooldown_s=0,
        protected_cidrs=(ipaddress.ip_network("172.16.0.0/12"),), **overrides,
    )
    ex = executor or FakeExecutor()
    eng = Engine(s, Journal(str(tmp_path)), ex)
    results = list(health) if isinstance(health, list) else None

    def fake_verify(inc):
        if results is None:
            ok = health(ex)  # sain selon les actions déjà jouées
        else:
            ok = results.pop(0) if len(results) > 1 else results[0]
        eng.journal.add(inc, "verify", ok=ok)
        return ok, {"ok": ok}

    monkeypatch.setattr(eng, "_verify", fake_verify)
    return eng, ex


def wait_closed(eng, inc, timeout=5):
    end = time.time() + timeout
    while inc["status"] == "IN_PROGRESS" and time.time() < end:
        time.sleep(0.02)
    return inc


def test_attaque_bloquee_puis_preuve_canary(tmp_path, monkeypatch):
    eng, ex = make_engine(tmp_path, monkeypatch, [True])
    inc, created = eng.submit(req_of())
    assert created and wait_closed(eng, inc)["status"] == "RESOLVED"
    assert inc["resolved_by"] == "block_ip" and ex.calls == ["block_ip"]
    assert "192.168.137.2" in eng.blocks
    assert (tmp_path / inc["id"] / "block_ip.json").exists()  # contrat de l'interface (b)
    assert inc["signal"]["suspects"][0]["value"] == "192.168.137.2"  # lu par le dashboard


def test_escalade_si_le_canary_echoue(tmp_path, monkeypatch):
    # malade après le blocage, sain après le redémarrage
    eng, ex = make_engine(tmp_path, monkeypatch, lambda ex: "restart" in ex.calls)
    inc, _ = eng.submit(req_of())
    assert wait_closed(eng, inc)["status"] == "RESOLVED"
    assert ex.calls == ["block_ip", "restart"] and inc["resolved_by"] == "restart"


def test_restart_demande_puis_recreate_puis_humain(tmp_path, monkeypatch):
    eng, ex = make_engine(tmp_path, monkeypatch, [False])
    inc, _ = eng.submit(req_of(remediation="restart"))
    assert wait_closed(eng, inc)["status"] == "UNRESOLVED"
    assert ex.calls == ["restart", "recreate"]  # jamais de rollback_vm sans demande explicite
    assert [e["event"] for e in inc["timeline"]][-1] == "escalated"


def test_rollback_vm_demande_n_escalade_pas(tmp_path, monkeypatch):
    eng, ex = make_engine(tmp_path, monkeypatch, [True])
    inc, _ = eng.submit(req_of(remediation="rollback_vm"))
    assert wait_closed(eng, inc)["resolved_by"] == "rollback_vm" and ex.calls == ["rollback_vm"]


def test_auto_service_sain_n_agit_pas(tmp_path, monkeypatch):
    eng, ex = make_engine(tmp_path, monkeypatch, [True])
    inc, _ = eng.submit(req_of(remediation="auto", scenario="injection"))
    assert wait_closed(eng, inc)["resolved_by"] == "none" and ex.calls == []


def test_auto_dos_bloque_sans_verifier_avant(tmp_path, monkeypatch):
    eng, ex = make_engine(tmp_path, monkeypatch, [True])
    inc, _ = eng.submit(req_of(remediation="auto", scenario="dos"))
    assert wait_closed(eng, inc)["resolved_by"] == "block_ip" and ex.calls == ["block_ip"]


def test_tout_echoue_donne_unresolved(tmp_path, monkeypatch):
    eng, ex = make_engine(tmp_path, monkeypatch, [False], executor=FakeExecutor(fail={"block_ip"}))
    inc, _ = eng.submit(req_of())
    assert wait_closed(eng, inc)["status"] == "UNRESOLVED"
    assert [e["event"] for e in inc["timeline"]][-1] == "escalated"
    assert ex.calls == ["block_ip", "restart", "recreate"]


def test_mapping_labels_comme_receiver():
    assert make_req(make_alert(remediation="auto", scenario="dos"))[0].action == "block_ip"
    assert make_req(make_alert(remediation="auto", scenario="exfiltration"))[0].action == "isolate"
    assert make_req(make_alert(remediation="auto", scenario="inconnu"))[0].action == "restart"
    assert make_req(make_alert(remediation="restore_db"))[0].target == "db"
    assert make_req(make_alert(remediation="restart", service=""))[0].service == "api"  # service par défaut
    assert make_req(make_alert(remediation="none"))[1] == "aucune_action"


def test_refus_ip_et_service_dangereux():
    assert make_req(make_alert(client_ip="172.18.0.5"))[1] == "reseau_protege"  # réseau Docker : le canary y est
    assert make_req(make_alert(client_ip="pas-une-ip; rm -rf /"))[1] == "ip_invalide"
    assert make_req(make_alert(client_ip=""))[1] == "client_ip_manquant"
    assert make_req(make_alert(remediation="restart", service="db; reboot"))[1] == "service_hors_liste"


def test_meme_alerte_ou_incident_en_cours_ne_relance_rien(tmp_path, monkeypatch):
    eng, ex = make_engine(tmp_path, monkeypatch, [False])
    inc, created = eng.submit(req_of(name="x1"))
    again, created2 = eng.submit(req_of(name="x1"))
    other, created3 = eng.submit(req_of(name="x2", remediation="restart"))
    assert created and not created2 and not created3 and again["id"] == other["id"] == inc["id"]
    wait_closed(eng, inc)


def test_anti_rebond_meme_action_meme_cible(tmp_path, monkeypatch):
    eng, ex = make_engine(tmp_path, monkeypatch, [False], action_cooldown_s=90)
    inc, _ = eng.submit(req_of(name="a", remediation="restart"))
    wait_closed(eng, inc)
    _, created = eng.submit(req_of(name="b", remediation="restart"))  # autre alerte, même (restart, api)
    assert not created
    _, created = eng.submit(req_of(name="c", remediation="restart", service="auth"))  # autre cible : passe
    assert created


def test_blocage_expire(tmp_path, monkeypatch):
    eng, ex = make_engine(tmp_path, monkeypatch, [True], block_ttl_s=0)
    inc, _ = eng.submit(req_of())
    wait_closed(eng, inc)
    eng.expire_blocks()
    assert eng.blocks == {} and ex.calls[-1] == "unblock"


def test_journal_survit_au_redemarrage_et_marque_l_interrompu(tmp_path):
    j = Journal(str(tmp_path))
    inc = j.create(req_of().as_signal())
    j2 = Journal(str(tmp_path))
    assert j2.incidents[inc["id"]]["status"] == "UNRESOLVED"


# ---------- Executor ansible ----------

class FakeRun:
    def __init__(self, rc=0, out="PLAY RECAP\nSERVICE RÉTABLI — api ok\n"):
        self.rc, self.out, self.cmd, self.kw = rc, out, None, None

    def __call__(self, cmd, **kw):
        self.cmd, self.kw = cmd, kw
        return subprocess.CompletedProcess(cmd, self.rc, self.out, "")


def test_ansible_commande_et_succes(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(subprocess, "run", fake)
    ex = AnsibleExecutor(dataclasses.replace(base_settings, ansible_inventory=""))
    res = ex.run("block_ip", "i1", {"ip": "203.0.113.9", "block_ips": ["203.0.113.9"]})
    assert fake.cmd == ["ansible-playbook", "remediation/block_ip.yml", "-e", "ip=203.0.113.9"]
    assert fake.kw["cwd"] == "/work" and res["rc"] == 0
    ex.run("restart", "i1", {"service": "api"})
    assert fake.cmd == ["ansible-playbook", "remediation/restart.yml", "-e", "service=api"]


def test_ansible_echec_si_rc_ou_marqueur_absent(monkeypatch):
    ex = AnsibleExecutor(dataclasses.replace(base_settings, ansible_inventory=""))
    monkeypatch.setattr(subprocess, "run", FakeRun(rc=2))
    with pytest.raises(ActionError):
        ex.run("restart", "i1", {"service": "api"})
    monkeypatch.setattr(subprocess, "run", FakeRun(rc=0, out="ok mais sans marqueur"))
    with pytest.raises(ActionError):
        ex.run("restart", "i1", {"service": "api"})


# ---------- HTTP ----------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ALERT_WEBHOOK_TOKEN", "jeton-de-test")
    from fastapi.testclient import TestClient

    from app import main

    monkeypatch.setattr(main, "settings", dataclasses.replace(
        base_settings, incidents_dir=str(tmp_path), action_cooldown_s=0, cooldown_s=0,
        protected_cidrs=(ipaddress.ip_network("172.16.0.0/12"),)))
    monkeypatch.setattr(main, "make_executor", lambda s: FakeExecutor())
    with TestClient(main.app) as c:
        monkeypatch.setattr(main.engine, "_verify", lambda inc: (True, {"ok": True}))
        yield c


AUTH = {"Authorization": "Bearer jeton-de-test"}


def webhook(*alerts):
    return {"version": "4", "status": "firing", "alerts": list(alerts)}


def test_http_token_obligatoire(client):
    body = webhook(make_alert())
    assert client.post("/api/v1/alerts", json=body).status_code == 401
    assert client.post("/api/v1/alerts", json=body, headers={"Authorization": "Bearer faux"}).status_code == 401
    assert client.get("/v1/incidents").status_code == 401
    assert client.post("/v1/anomalies", json=body, headers=AUTH).status_code == 404  # ancienne entrée retirée


def test_http_200_puis_lecture(client):
    r = client.post("/api/v1/alerts", json=webhook(make_alert()), headers=AUTH)
    assert r.status_code == 200
    time.sleep(0.5)
    incidents = client.get("/v1/incidents", headers=AUTH).json()
    assert len(incidents) == 1 and incidents[0]["status"] == "RESOLVED"
    assert "remediation_incidents_total" in client.get("/metrics").text


def test_http_seules_les_alertes_firing_agissent(client):
    r = client.post("/api/v1/alerts", json=webhook(make_alert(status="resolved")), headers=AUTH)
    assert r.status_code == 200
    time.sleep(0.2)
    assert client.get("/v1/incidents", headers=AUTH).json() == []


def test_sans_canary_la_verification_est_deleguee_au_playbook(tmp_path):
    s = dataclasses.replace(base_settings, incidents_dir=str(tmp_path), canary_url="", action_cooldown_s=0, cooldown_s=0)
    eng = Engine(s, Journal(str(tmp_path)), FakeExecutor())
    inc, _ = eng.submit(req_of(remediation="restart"))
    assert wait_closed(eng, inc)["resolved_by"] == "restart"  # pas d'escalade à tort après une action réussie
    # ...mais une vérification déléguée ne peut pas écarter une alerte « auto » comme faux positif
    inc2, _ = eng.submit(req_of(name="n2", remediation="auto", scenario="injection"))
    assert wait_closed(eng, inc2)["resolved_by"] == "restart"


def test_unblock_ip_n_exige_pas_le_marqueur(monkeypatch, tmp_path):
    (tmp_path / "remediation").mkdir()
    (tmp_path / "remediation" / "unblock_ip.yml").write_text("---\n")
    fake = FakeRun(rc=0, out="PLAY RECAP ok")
    monkeypatch.setattr(subprocess, "run", fake)
    ex = AnsibleExecutor(dataclasses.replace(base_settings, ansible_workdir=str(tmp_path), ansible_inventory=""))
    ex.unblock(["203.0.113.9"], [])
    assert fake.cmd[1] == "remediation/unblock_ip.yml"
