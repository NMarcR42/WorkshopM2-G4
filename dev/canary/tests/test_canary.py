import functools

import httpx
import pytest

from app import probe
from app.config import settings


def fake_waf(monkeypatch, handler):
    """Remplace le réseau par un faux WAF : le test ne dépend d'aucun service."""
    real = httpx.Client
    monkeypatch.setattr(probe.httpx, "Client", functools.partial(real, transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(probe, "settings", settings.__class__(waf_url="http://waf.test"))


def healthy(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/auth/login":
        return httpx.Response(200, json={"access_token": "jeton"})
    if path == "/api/v1/transactions":
        assert request.headers["authorization"] == "Bearer jeton"
        assert request.headers["idempotency-key"].startswith("canary-")
        return httpx.Response(201, json={"status": "COMPLETED"})
    if path == "/api/v1/ledger/check":
        return httpx.Response(200, json={"consistent": True, "mismatches": []})
    return httpx.Response(404)


def test_parcours_sain(monkeypatch):
    monkeypatch.setenv("CANARY_PASSWORD", "x")
    fake_waf(monkeypatch, healthy)
    r = probe.run_probe()
    assert r["ok"] and r["failed_step"] is None
    assert [s["step"] for s in r["steps"]] == ["login", "transaction", "ledger"]


def test_cle_d_idempotence_change_a_chaque_passe(monkeypatch):
    monkeypatch.setenv("CANARY_PASSWORD", "x")
    keys = []

    def handler(request):
        if request.url.path == "/api/v1/transactions":
            keys.append(request.headers["idempotency-key"])
        return healthy(request)

    fake_waf(monkeypatch, handler)
    probe.run_probe()
    probe.run_probe()
    assert len(set(keys)) == 2


def test_api_en_panne_est_un_echec_a_l_etape_transaction(monkeypatch):
    monkeypatch.setenv("CANARY_PASSWORD", "x")
    fake_waf(monkeypatch, lambda r: httpx.Response(503) if r.url.path.endswith("/transactions") else healthy(r))
    r = probe.run_probe()
    assert not r["ok"] and r["failed_step"] == "transaction" and "503" in r["detail"]


def test_ledger_incoherent_est_un_echec(monkeypatch):
    monkeypatch.setenv("CANARY_PASSWORD", "x")
    fake_waf(
        monkeypatch,
        lambda r: httpx.Response(200, json={"consistent": False, "mismatches": ["ACC-ALICE"]})
        if r.url.path.endswith("/ledger/check")
        else healthy(r),
    )
    r = probe.run_probe()
    assert not r["ok"] and r["failed_step"] == "ledger" and "ACC-ALICE" in r["detail"]


def test_waf_injoignable_ne_plante_pas(monkeypatch):
    monkeypatch.setenv("CANARY_PASSWORD", "x")

    def down(request):
        raise httpx.ConnectError("refus")

    fake_waf(monkeypatch, down)
    r = probe.run_probe()
    assert not r["ok"] and r["failed_step"] == "login"


def test_sans_mot_de_passe_ou_sans_waf_echec_explicite(monkeypatch):
    monkeypatch.delenv("CANARY_PASSWORD", raising=False)
    monkeypatch.delenv("CANARY_PASSWORD_FILE", raising=False)
    fake_waf(monkeypatch, healthy)
    assert "mot de passe" in probe.run_probe()["detail"]


def test_verify_et_metrique(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main

    monkeypatch.setenv("CANARY_PASSWORD", "x")
    monkeypatch.setattr(main, "_loop", lambda stop: None)  # pas de boucle de fond pendant le test
    fake_waf(monkeypatch, healthy)
    with TestClient(main.app) as c:
        body = c.post("/verify").json()
        assert body["ok"] is True
        assert "payment_probe_success 1.0" in c.get("/metrics").text
        fake_waf(monkeypatch, lambda r: httpx.Response(500))
        assert c.post("/verify").json()["ok"] is False
        assert "payment_probe_success 0.0" in c.get("/metrics").text
        assert c.get("/health").status_code == 200


@pytest.fixture(autouse=True)
def _no_real_secret(monkeypatch):
    monkeypatch.delenv("CANARY_PASSWORD_FILE", raising=False)
