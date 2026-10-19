import os
import time

import jwt

from app import config
from app.users import load_users

SECRET = os.environ["JWT_SECRET"]


def login(client, username="alice", password="alice-demo"):
    return client.post("/login", json={"username": username, "password": password})


def test_login_ok_renvoie_un_jeton_conforme_au_contrat_de_l_api(client):
    r = login(client)
    assert r.status_code == 200
    body = r.json()
    # L'API exige : HS256, claims sub / exp / role avec role dans {client, operator, canary}.
    claims = jwt.decode(body["access_token"], SECRET, algorithms=["HS256"], options={"require": ["exp", "sub"]})
    assert claims["sub"] == "alice"
    assert claims["role"] == "client"
    assert claims["exp"] > time.time()
    assert body["role"] == "client" and body["expires_in"] == config.settings.token_ttl_s


def test_operateur(client):
    r = login(client, "ops", "ops-demo")
    assert r.status_code == 200 and r.json()["role"] == "operator"


def test_mauvais_mot_de_passe_401(client):
    assert login(client, password="faux").status_code == 401


def test_utilisateur_inconnu_401_meme_message(client):
    inconnu, mauvais = login(client, "personne", "x"), login(client, password="faux")
    assert inconnu.status_code == mauvais.status_code == 401
    assert inconnu.json() == mauvais.json()  # on ne révèle pas quels comptes existent


def test_champs_manquants_422(client):
    assert client.post("/login", json={"username": "alice"}).status_code == 422


def test_health_et_metriques(client):
    login(client, password="faux")
    assert client.get("/health").json() == {"status": "ok"}
    assert 'auth_logins_total{result="failed"}' in client.get("/metrics").text


def test_compte_canary_seulement_si_mot_de_passe_fourni(monkeypatch):
    assert "canary" not in load_users()
    monkeypatch.setenv("CANARY_PASSWORD", "mot-de-passe-de-test")
    assert load_users()["canary"]["role"] == "canary"
