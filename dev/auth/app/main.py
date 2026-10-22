import time
from contextlib import asynccontextmanager

import jwt
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from . import face, observability
from .config import settings
from .observability import LOGINS, client_ip, log
from .passwords import DUMMY_HASH, verify_password
from .users import load_users

users: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    observability.setup_logging()
    users.update(load_users())
    yield


app = FastAPI(title="Auth (fictif)", version="0.1.0", lifespan=lifespan)
observability.install(app)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    username: str
    role: str


# Contrat infra : le préfixe /auth est CONSERVÉ par le gateway. Les chemins sans préfixe restent servis (masqués de /docs)
# pour le front de dev et le WAF local, qui retirent encore le préfixe.
@app.post("/auth/login", response_model=TokenOut)
@app.post("/login", response_model=TokenOut, include_in_schema=False)
def login(body: LoginIn, request: Request, x_face_token: str | None = Header(default=None)):
    """Échange identifiant + mot de passe contre un JWT que l'API vérifie elle-même."""
    user = users.get(body.username)
    # Le compte technique "canary" (sonde de vérification) n'a pas de visage : il est exempté du contrôle facial.
    need_face = settings.face_enforce and not (user and user["role"] == "canary")
    if need_face and not x_face_token:
        # Refus avant tout calcul de hash : sans visage reconnu, inutile de tester un mot de passe.
        log.warning("login_face_missing", extra={"extra_fields": {
            "event": "login_face_missing", "username": body.username[:50], "client_ip": client_ip(request)}})
        raise HTTPException(403, "Vérification faciale requise")
    # On vérifie toujours un hash, même si l'utilisateur n'existe pas (voir DUMMY_HASH).
    valid = verify_password(body.password, user["password_hash"] if user else DUMMY_HASH) and bool(user)
    if need_face:
        # Valide le token auprès de l'IA (usage unique, lié à l'utilisateur) et lui donne le résultat du mot de passe.
        try:
            face.confirm(body.username, x_face_token, valid)
        except face.FaceRejected:
            log.warning("login_face_rejected", extra={"extra_fields": {
                "event": "login_face_rejected", "username": body.username[:50], "client_ip": client_ip(request)}})
            raise HTTPException(403, "Vérification faciale absente ou expirée, recommencez") from None
        except face.FaceUnavailable as e:
            log.error("login_face_unavailable", extra={"extra_fields": {"event": "login_face_unavailable", "error": str(e)}})
            # Fail closed : on ne délivre pas de JWT sans pouvoir vérifier. Le plan B se décide à l'extérieur (FACE_ENFORCE=false).
            raise HTTPException(503, "Service de reconnaissance faciale indisponible") from None
    if not valid:
        LOGINS.labels("failed").inc()
        # Journal exploité par le SIEM (rafales d'échecs = force brute). Jamais le mot de passe.
        log.warning("login_failed", extra={"extra_fields": {
            "event": "login_failed", "username": body.username[:50], "client_ip": client_ip(request)}})
        # Même message pour "inconnu" et "mauvais mot de passe".
        raise HTTPException(401, "Identifiants invalides")

    now = int(time.time())
    # Contrat avec l'API (voir dev/api/README.md) : sub = propriétaire des comptes, exp, role.
    claims = {"sub": body.username, "role": user["role"], "iat": now, "exp": now + settings.token_ttl_s}
    token = jwt.encode(claims, settings.jwt_secret, algorithm="HS256")
    LOGINS.labels("ok").inc()
    log.info("login_ok", extra={"extra_fields": {
        "event": "login_ok", "username": body.username, "client_ip": client_ip(request)}})
    return TokenOut(access_token=token, expires_in=settings.token_ttl_s, username=body.username, role=user["role"])


@app.get("/auth/health", include_in_schema=False)
@app.get("/health", include_in_schema=False)
def health():
    """Le process répond. Rien d'autre à vérifier : auth n'a pas de base de données."""
    return {"status": "ok"}
