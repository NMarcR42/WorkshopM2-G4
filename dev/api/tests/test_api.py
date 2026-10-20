import uuid

from .conftest import needs_db, token

TX = {"from_account": "ACC-CANARY-A", "to_account": "ACC-CANARY-B", "amount": "1.00", "currency": "EUR"}


# --- sans base de donnees -------------------------------------------------------------

def test_health_ne_depend_pas_de_la_base(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_metrics_exposees(client):
    client.get("/health")
    body = client.get("/metrics").text
    assert "http_requests_total" in body and "http_request_duration_seconds" in body


def test_transaction_sans_jeton_401(client):
    assert client.post("/v1/transactions", json=TX).status_code == 401


def test_jeton_expire_401(client):
    assert client.post("/v1/transactions", json=TX, headers=token("canary", "canary", ttl=-10)).status_code == 401


def test_role_inconnu_403(client):
    assert client.post("/v1/transactions", json=TX, headers=token("x", "root")).status_code == 403


def test_validation_montant_negatif_422(client):
    r = client.post("/v1/transactions", json={**TX, "amount": "-5"}, headers=token("canary", "canary"))
    assert r.status_code == 422


def test_validation_memes_comptes_422(client):
    r = client.post("/v1/transactions", json={**TX, "to_account": TX["from_account"]}, headers=token("canary", "canary"))
    assert r.status_code == 422


def test_ledger_reserve_aux_operateurs(client):
    assert client.get("/v1/ledger/check", headers=token("alice", "client")).status_code == 403


# --- avec base de donnees (TEST_DB_HOST) ----------------------------------------------

@needs_db
def test_ready(client):
    assert client.get("/ready").status_code == 200


@needs_db
def test_transaction_ok_puis_lecture(client):
    r = client.post("/v1/transactions", json=TX, headers=token("canary", "canary"))
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "COMPLETED"
    got = client.get(f"/v1/transactions/{body['id']}", headers=token("canary", "canary"))
    assert got.status_code == 200 and got.json()["id"] == body["id"]


@needs_db
def test_idempotence(client):
    headers = {**token("canary", "canary"), "Idempotency-Key": str(uuid.uuid4())}
    first = client.post("/v1/transactions", json=TX, headers=headers)
    second = client.post("/v1/transactions", json=TX, headers=headers)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


@needs_db
def test_solde_insuffisant_422(client):
    r = client.post("/v1/transactions", json={**TX, "from_account": "ACC-BOB", "to_account": "ACC-MERCHANT", "amount": "99999"},
                    headers=token("bob", "client"))
    assert r.status_code == 422


@needs_db
def test_client_ne_peut_pas_debiter_le_compte_dun_autre(client):
    r = client.post("/v1/transactions", json={**TX, "from_account": "ACC-BOB", "to_account": "ACC-MERCHANT"},
                    headers=token("alice", "client"))
    assert r.status_code == 403


@needs_db
def test_liste_des_comptes_limitee_au_proprietaire(client):
    mine = client.get("/v1/accounts", headers=token("alice", "client"))
    assert mine.status_code == 200
    assert [a["id"] for a in mine.json()] == ["ACC-ALICE"]
    everyone = client.get("/v1/accounts", headers=token("ops", "operator")).json()
    assert {"ACC-ALICE", "ACC-BOB"} <= {a["id"] for a in everyone}


def test_liste_des_comptes_sans_jeton_401(client):
    assert client.get("/v1/accounts").status_code == 401


@needs_db
def test_compte_inconnu_404(client):
    r = client.post("/v1/transactions", json={**TX, "to_account": "ACC-NOPE"}, headers=token("canary", "canary"))
    assert r.status_code == 404


@needs_db
def test_grand_livre_coherent_apres_transactions(client):
    for _ in range(3):
        client.post("/v1/transactions", json=TX, headers=token("canary", "canary"))
    check = client.get("/v1/ledger/check", headers=token("ops", "operator")).json()
    assert check == {"consistent": True, "mismatches": []}


# ---------- contrat infra : préfixe conservé et transaction de contrôle ----------

def test_prefixe_api_conserve(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/v1/accounts").status_code == 401  # la route existe sous /api (401 et non 404)
    assert "/api/v1/transactions" in client.get("/openapi.json").text


def test_synthetique_ferme_sans_secret_ou_sans_bon_jeton(client, monkeypatch):
    body = {"amount": 1.0, "currency": "EUR", "label": "t"}
    monkeypatch.delenv("SYNTHETIC_PROBE_TOKEN", raising=False)
    assert client.post("/api/synthetic/transaction", json=body).status_code == 503
    monkeypatch.setenv("SYNTHETIC_PROBE_TOKEN", "bon")
    assert client.post("/api/synthetic/transaction", json=body).status_code == 401
    assert client.post("/api/synthetic/transaction", json=body, headers={"Authorization": "Bearer faux"}).status_code == 401
    # un JWT client n'est pas un jeton de sonde
    assert client.post("/api/synthetic/transaction", json=body, headers=token("alice", "client")).status_code == 401


def test_synthetique_echoue_si_auth_tombe(client, monkeypatch):
    from app import synthetic
    monkeypatch.setenv("SYNTHETIC_PROBE_TOKEN", "bon")
    monkeypatch.setattr(synthetic, "settings", synthetic.settings.__class__(auth_url="http://auth.invalid"))
    r = client.post("/api/synthetic/transaction", json={"amount": 1.0, "currency": "EUR"},
                    headers={"Authorization": "Bearer bon"})
    assert r.status_code == 503


@needs_db
def test_synthetique_traverse_auth_et_base(client, monkeypatch):
    import httpx

    from app import synthetic
    monkeypatch.setenv("SYNTHETIC_PROBE_TOKEN", "bon")
    monkeypatch.setattr(synthetic, "settings", synthetic.settings.__class__(auth_url="http://auth.test"))
    monkeypatch.setattr(synthetic.httpx, "get", lambda url, **kw: httpx.Response(200, json={"status": "ok"}))
    r = client.post("/api/synthetic/transaction", json={"amount": 1.0, "currency": "EUR", "label": "t"},
                    headers={"Authorization": "Bearer bon"})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert client.get("/api/v1/ledger/check", headers=token("ops", "operator")).json()["consistent"] is True
