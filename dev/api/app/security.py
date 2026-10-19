"""Authentification : JWT HS256 emis par le service auth, verifie localement.

Verification locale (secret partage) : une panne du service auth n'arrete pas les paiements
des utilisateurs deja connectes.
"""
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

bearer = HTTPBearer(auto_error=False)
ROLES = {"client", "operator", "canary"}


@dataclass(frozen=True)
class User:
    sub: str
    role: str


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
    if creds is None:
        raise HTTPException(401, "Authentification requise", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = jwt.decode(
            creds.credentials,
            settings.jwt_secret,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError:
        raise HTTPException(401, "Jeton invalide ou expire", headers={"WWW-Authenticate": "Bearer"})
    role = claims.get("role")
    if role not in ROLES:
        raise HTTPException(403, "Role inconnu")
    return User(sub=claims["sub"], role=role)


def require_role(*allowed: str):
    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(403, "Droits insuffisants")
        return user

    return dependency
