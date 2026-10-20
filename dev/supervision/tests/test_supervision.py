from datetime import datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)

OK = {"reachable": True, "ok": True, "stale": False, "age_s": 1}
KO = {**OK, "ok": False}


def iso(seconds_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def inc(status, ended_ago=None):
    return {"id": "i", "status": status, "ended_at": iso(ended_ago) if ended_ago is not None else None}


def test_etats_du_bandeau():
    assert main.global_state(OK, []) == "HEALTHY"
    assert main.global_state(KO, []) == "DEGRADED"
    assert main.global_state(OK, [inc("IN_PROGRESS")]) == "REMEDIATING"
    assert main.global_state(OK, [inc("RESOLVED", 10)]) == "RECOVERED"
    assert main.global_state(OK, [inc("RESOLVED", 600)]) == "HEALTHY"


def test_sans_sonde_fraiche_on_ne_dit_pas_sain():
    assert main.global_state({"reachable": False}, []) == "UNKNOWN"
    assert main.global_state({**OK, "stale": True}, []) == "UNKNOWN"


def test_status_agrege(monkeypatch):
    monkeypatch.setattr(main, "read_probe", lambda: OK)
    monkeypatch.setattr(main, "read_incidents", lambda limit=10: None)
    body = client.get("/api/status").json()
    assert body["state"] == "HEALTHY" and body["engine_reachable"] is False and body["incidents"] == []


def test_resume_d_incident_calcule_la_duree():
    s = main._summary({"id": "i", "status": "RESOLVED", "target_service": "api", "created_at": iso(30), "ended_at": iso(18),
                       "resolved_by": "restart_service", "signal": {"score": 0.9, "suspects": []}, "timeline": []})
    assert 11 <= s["duration_s"] <= 13


def test_historique_tolere_prometheus_absent(monkeypatch):
    def down(*a, **k):
        raise httpx.ConnectError("refus")

    monkeypatch.setattr(main.httpx, "get", down)
    body = client.get("/api/history").json()
    assert body["series"] == {"probe": [], "rps": [], "p95_ms": []}


def test_historique_ignore_les_nan(monkeypatch):
    class R:
        def raise_for_status(self): ...
        def json(self):
            return {"data": {"result": [{"values": [[1, "1"], [2, "NaN"], [3, "0"]]}]}}

    monkeypatch.setattr(main.httpx, "get", lambda *a, **k: R())
    assert client.get("/api/history").json()["series"]["probe"] == [[1.0, 1.0], [3.0, 0.0]]


def test_lecture_seule():
    assert client.post("/api/status").status_code in (404, 405)
    assert client.get("/health").status_code == 200


# ---------- sources de l'infra : Alertmanager et Loki ----------

class Resp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self): ...
    def json(self):
        return self.data


def with_settings(monkeypatch, **kw):
    import dataclasses
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, **kw))


def test_alertes_lues_sur_alertmanager(monkeypatch):
    with_settings(monkeypatch, alertmanager_url="http://am:9093", prometheus_url="http://prom:9090")
    monkeypatch.setattr(main.httpx, "get", lambda url, **k: Resp(
        [{"labels": {"alertname": "AnomalieDetecteeML", "service": "api", "remediation": "auto"}, "startsAt": "2026-01-01T00:00:00Z"}]))
    body = client.get("/api/alerts").json()
    assert body["source"] == "alertmanager" and body["alerts"][0]["name"] == "AnomalieDetecteeML"


def test_alertes_repli_sur_prometheus_si_alertmanager_tombe(monkeypatch):
    with_settings(monkeypatch, alertmanager_url="http://am:9093", prometheus_url="http://prom:9090")

    def get(url, **k):
        if "9093" in url:
            raise httpx.ConnectError("refus")
        assert k["params"]["query"] == 'ALERTS{alertstate="firing"}'
        return Resp({"data": {"result": [{"metric": {"alertname": "ApiDown", "alertstate": "firing"}}]}})

    monkeypatch.setattr(main.httpx, "get", get)
    body = client.get("/api/alerts").json()
    assert body["source"] == "prometheus" and body["alerts"][0]["name"] == "ApiDown"


def test_alertes_aucune_source_ne_plante_pas(monkeypatch):
    with_settings(monkeypatch, alertmanager_url="", prometheus_url="")
    assert client.get("/api/alerts").json() == {"source": None, "reachable": False, "alerts": []}


def test_journal_de_remediation_loki(monkeypatch):
    with_settings(monkeypatch, loki_url="http://loki:3100", loki_remediation_label="syslog_identifier=ra-remediate")
    seen = {}

    def get(url, **k):
        seen.update(k["params"])
        return Resp({"data": {"result": [{"values": [["1700000000000000000", '{"msg":"action_done"}'],
                                                     ["1700000005000000000", "ligne systemd brute"]]}]}})

    monkeypatch.setattr(main.httpx, "get", get)
    body = client.get("/api/remediation-log").json()
    assert seen["query"] == '{syslog_identifier="ra-remediate"}'
    assert [x["event"] for x in body["lines"]] == [None, "action_done"]  # plus récent d'abord


def test_journal_non_configure_ou_loki_tombe(monkeypatch):
    with_settings(monkeypatch, loki_url="", loki_remediation_label="")
    assert client.get("/api/remediation-log").json()["configured"] is False
    with_settings(monkeypatch, loki_url="http://loki:3100", loki_remediation_label="service=remediation")
    monkeypatch.setattr(main.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("refus")))
    body = client.get("/api/remediation-log").json()
    assert body["configured"] and not body["reachable"] and body["lines"] == []


def test_etiquette_loki_invalide_refusee(monkeypatch):
    with_settings(monkeypatch, loki_url="http://loki:3100", loki_remediation_label='service=x"} or {job=~".+"')
    assert client.get("/api/remediation-log").json()["configured"] is False
