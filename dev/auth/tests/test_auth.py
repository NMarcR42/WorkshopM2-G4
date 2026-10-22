import os
import time

import jwt
import pytest

from app import config, face
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


def test_prefixe_auth_conserve(client):
    assert client.get("/auth/health").json() == {"status": "ok"}
    assert client.post("/auth/login", json={"username": "alice", "password": "alice-demo"}).status_code == 200


# --- Contrôle facial (FACE_ENFORCE) : le service IA est simulé, aucun appel réseau ---

@pytest.fixture
def enforce():
    # Settings est figé (frozen) : on contourne pour le test et on restaure ensuite.
    object.__setattr__(config.settings, "face_enforce", True)
    yield
    object.__setattr__(config.settings, "face_enforce", False)


def login_face(client, token=None, **kw):
    headers = {"X-Face-Token": token} if token else {}
    return client.post("/login", json={"username": kw.get("u", "alice"), "password": kw.get("p", "alice-demo")}, headers=headers)


def test_enforce_sans_token_403_et_pas_de_jwt(client, enforce):
    r = login_face(client)
    assert r.status_code == 403 and "access_token" not in r.json()


def test_enforce_token_valide_donne_le_jwt(client, enforce, monkeypatch):
    appels = []
    monkeypatch.setattr(face, "confirm", lambda u, t, ok: appels.append((u, t, ok)))
    assert login_face(client, "tok").status_code == 200
    assert appels == [("alice", "tok", True)]


def test_enforce_token_refuse_par_l_ia_403(client, enforce, monkeypatch):
    def refuse(*a):
        raise face.FaceRejected()
    monkeypatch.setattr(face, "confirm", refuse)
    assert login_face(client, "faux").status_code == 403


def test_enforce_ia_injoignable_503_propre(client, enforce, monkeypatch):
    def panne(*a):
        raise face.FaceUnavailable("down")
    monkeypatch.setattr(face, "confirm", panne)
    assert login_face(client, "tok").status_code == 503


def test_enforce_mauvais_mot_de_passe_401_et_ia_prevenue(client, enforce, monkeypatch):
    appels = []
    monkeypatch.setattr(face, "confirm", lambda u, t, ok: appels.append(ok))
    assert login_face(client, "tok", p="faux").status_code == 401
    assert appels == [False]


def test_enforce_n_exempte_pas_les_autres_comptes_mais_exempte_canary(client, enforce, monkeypatch):
    monkeypatch.setitem(__import__("app.main", fromlist=["users"]).users, "canary",
                        {"role": "canary", "password_hash": load_users()["alice"]["password_hash"]})
    assert login_face(client, u="canary", p="alice-demo").status_code == 200  # pas de token, pas d'appel IA


def test_sans_enforce_le_header_est_ignore(client):
    assert login_face(client).status_code == 200
