"""Transaction de contrôle de l'infra : POST /api/synthetic/transaction.

C'est la preuve de reprise officielle (sondes et vérification post-remédiation) : elle traverse auth, api et base.
Jeton dédié (synthetic_probe_token), distinct des JWT clients : la sonde n'a aucun droit de client.
"""
import hmac
from decimal import Decimal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from . import db
from .config import settings
from .routes import apply_transfer

router = APIRouter(prefix="/synthetic")


class SyntheticIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    currency: str = Field("EUR", pattern=r"^[A-Z]{3}$")
    label: str = Field("", max_length=100)


@router.post("/transaction")
def synthetic_transaction(body: SyntheticIn, authorization: str | None = Header(None)):
    expected = settings.synthetic_probe_token
    if not expected:
        # Sans secret, la route reste fermée : jamais ouverte par défaut.
        raise HTTPException(503, "Transaction de contrôle non configurée")
    # compare_digest : temps constant, pas d'indice sur le jeton par la durée de réponse.
    if not authorization or not hmac.compare_digest(authorization.encode(), f"Bearer {expected}".encode()):
        raise HTTPException(401, "Jeton de sonde invalide", headers={"WWW-Authenticate": "Bearer"})
    if not settings.auth_url:
        raise HTTPException(503, "AUTH_URL non défini")

    # 1) auth : la preuve doit échouer si le service d'authentification est tombé (il ne sert pas ce chemin sinon).
    try:
        r = httpx.get(f"{settings.auth_url}/auth/health", timeout=settings.synthetic_timeout_s)
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"auth injoignable ({type(exc).__name__})")
    if r.status_code != 200:
        raise HTTPException(503, f"auth en erreur (HTTP {r.status_code})")

    # 2) api + base : un vrai virement entre les comptes dédiés. Le sens s'inverse si A est vide, pour ne jamais s'épuiser.
    a, b = settings.synthetic_accounts
    with db.transaction() as conn:
        accounts = {row["id"]: row for row in conn.execute(
            "SELECT id, balance, currency FROM accounts WHERE id = ANY(%s) ORDER BY id FOR UPDATE", ([a, b],)).fetchall()}
        if len(accounts) != 2 or any(x["currency"] != body.currency for x in accounts.values()):
            raise HTTPException(503, "Comptes de contrôle absents ou devise incompatible")
        src, dst = (a, b) if accounts[a]["balance"] >= body.amount else (b, a)
        if accounts[src]["balance"] < body.amount:
            raise HTTPException(503, "Comptes de contrôle à sec")
        row = apply_transfer(conn, src, dst, body.amount, body.currency, "synthetic-probe", f"synthetic-{uuid4()}")
    return {"status": "ok", "transaction_id": str(row["id"]), "label": body.label, "amount": str(row["amount"])}
