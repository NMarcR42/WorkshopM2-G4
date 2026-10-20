import time
from contextlib import asynccontextmanager

import jwt
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from . import observability
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
def login(body: LoginIn, request: Request):
    """Échange identifiant + mot de passe contre un JWT que l'API vérifie elle-même."""
    user = users.get(body.username)
    # On vérifie toujours un hash, même si l'utilisateur n'existe pas (voir DUMMY_HASH).
    valid = verify_password(body.password, user["password_hash"] if user else DUMMY_HASH)
    if not user or not valid:
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
