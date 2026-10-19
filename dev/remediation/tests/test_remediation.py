import dataclasses
import ipaddress
import time

import pytest

from app.config import settings as base_settings
from app.engine import Engine
from app.executors import ActionError
from app.journal import Journal
from app.schemas import Signal


def make_signal(anomaly_id="a1", suspects=None, target="api"):
    return Signal(
        schema_version="1.0", anomaly_id=anomaly_id, detected_at="2026-10-21T14:03:12Z",
        detector={"name": "isolation_forest"}, score=0.9, consecutive_windows=3, target_service=target, window_s=10,
        suspects=suspects if suspects is not None else [{"kind": "ip", "value": "192.168.137.2", "share": 0.97}],
    )


class FakeExecutor:
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def run(self, action, incident_id, params):
        self.calls.append(action)
        if action in self.fail:
            raise ActionError("panne simulée")
        return {"changed": True}


def make_engine(tmp_path, monkeypatch, health, executor=None, **overrides):
    """health : liste de résultats successifs du canary (le dernier est répété)."""
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
    inc, created = eng.submit(make_signal())
    assert created and wait_closed(eng, inc)["status"] == "RESOLVED"
    assert inc["resolved_by"] == "block_source" and ex.calls == ["block_source"]
    assert "192.168.137.2" in eng.blocks
    assert (tmp_path / inc["id"] / "block_source.json").exists()  # contrat de l'interface (b)


def test_escalade_si_le_canary_echoue(tmp_path, monkeypatch):
    # malade après le blocage, sain après le redémarrage
    eng, ex = make_engine(tmp_path, monkeypatch, lambda ex: "restart_service" in ex.calls)
    inc, _ = eng.submit(make_signal())
    assert wait_closed(eng, inc)["status"] == "RESOLVED"
    assert ex.calls[0] == "block_source" and inc["resolved_by"] in ("restart_service", "rollback_service")


def test_rien_a_reparer_n_agit_pas(tmp_path, monkeypatch):
    eng, ex = make_engine(tmp_path, monkeypatch, [True])
    inc, _ = eng.submit(make_signal(suspects=[]))
    assert wait_closed(eng, inc)["resolved_by"] == "none" and ex.calls == []


def test_sans_suspect_et_service_casse_on_redemarre(tmp_path, monkeypatch):
    eng, ex = make_engine(tmp_path, monkeypatch, lambda ex: "restart_service" in ex.calls)
    inc, _ = eng.submit(make_signal(suspects=[]))
    assert wait_closed(eng, inc)["resolved_by"] == "restart_service" and ex.calls == ["restart_service"]


def test_tout_echoue_donne_unresolved(tmp_path, monkeypatch):
    eng, ex = make_engine(tmp_path, monkeypatch, [False], executor=FakeExecutor(fail={"block_source"}))
    inc, _ = eng.submit(make_signal())
    assert wait_closed(eng, inc)["status"] == "UNRESOLVED"
    assert [e["event"] for e in inc["timeline"]][-1] == "escalated"
    assert ex.calls == ["block_source", "restart_service", "rollback_service"]


def test_ip_protegee_ou_invalide_jamais_bloquee(tmp_path, monkeypatch):
    eng, _ = make_engine(tmp_path, monkeypatch, [True])
    sig = make_signal(suspects=[
        {"kind": "ip", "value": "172.18.0.5", "share": 0.99},     # réseau Docker protégé (le canary)
        {"kind": "ip", "value": "pas-une-ip; rm -rf /", "share": 0.9},
        {"kind": "ip", "value": "10.9.9.9", "share": 0.1},         # trop peu de trafic
    ])
    assert eng._blockable_ips(sig) == []


def test_meme_anomalie_ou_incident_en_cours_ne_relance_rien(tmp_path, monkeypatch):
    eng, ex = make_engine(tmp_path, monkeypatch, [False])
    inc, created = eng.submit(make_signal("x1"))
    again, created2 = eng.submit(make_signal("x1"))
    other, created3 = eng.submit(make_signal("x2"))
    assert created and not created2 and not created3 and again["id"] == other["id"] == inc["id"]
    wait_closed(eng, inc)


def test_blocage_expire(tmp_path, monkeypatch):
    eng, ex = make_engine(tmp_path, monkeypatch, [True], block_ttl_s=0)
    inc, _ = eng.submit(make_signal())
    wait_closed(eng, inc)
    eng.expire_blocks()
    assert eng.blocks == {} and ex.calls[-1] == "block_source"


def test_journal_survit_au_redemarrage_et_marque_l_interrompu(tmp_path):
    j = Journal(str(tmp_path))
    inc = j.create(make_signal().model_dump(mode="json"))
    j2 = Journal(str(tmp_path))
    assert j2.incidents[inc["id"]]["status"] == "UNRESOLVED"


# ---------- HTTP ----------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGINE_TOKEN", "jeton-de-test")
    from fastapi.testclient import TestClient

    from app import main

    monkeypatch.setattr(main, "settings", dataclasses.replace(base_settings, incidents_dir=str(tmp_path)))
    monkeypatch.setattr(main, "make_executor", lambda s: FakeExecutor())
    with TestClient(main.app) as c:
        monkeypatch.setattr(main.engine, "_verify", lambda inc: (True, {"ok": True}))
        yield c


AUTH = {"Authorization": "Bearer jeton-de-test"}


def test_http_token_obligatoire(client):
    body = make_signal().model_dump(mode="json")
    assert client.post("/v1/anomalies", json=body).status_code == 401
    assert client.post("/v1/anomalies", json=body, headers={"Authorization": "Bearer faux"}).status_code == 401
    assert client.get("/v1/incidents").status_code == 401


def test_http_service_hors_liste_fermee_422(client):
    body = make_signal().model_dump(mode="json") | {"target_service": "db"}
    assert client.post("/v1/anomalies", json=body, headers=AUTH).status_code == 422


def test_http_202_puis_lecture(client):
    r = client.post("/v1/anomalies", json=make_signal().model_dump(mode="json"), headers=AUTH)
    assert r.status_code == 202
    iid = r.json()["incident_id"]
    time.sleep(0.5)
    assert client.get(f"/v1/incidents/{iid}", headers=AUTH).json()["status"] == "RESOLVED"
    assert "remediation_incidents_total" in client.get("/metrics").text
