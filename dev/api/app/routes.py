from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response

from . import db
from .observability import TRANSACTIONS
from .schemas import AccountOut, LedgerCheck, TransactionIn, TransactionOut
from .security import User, require_role

router = APIRouter(prefix="/v1")

TX_COLUMNS = "id, from_account, to_account, amount, currency, status, created_by, created_at"


def apply_transfer(conn, from_account, to_account, amount, currency, created_by, idempotency_key=None) -> dict:
    """Débit + crédit + ligne `transactions`, dans la transaction SQL de l'appelant (comptes déjà verrouillés).
    Partagé avec la transaction de contrôle : la preuve de reprise passe par le même code que les vrais paiements."""
    conn.execute("UPDATE accounts SET balance = balance - %s WHERE id = %s", (amount, from_account))
    conn.execute("UPDATE accounts SET balance = balance + %s WHERE id = %s", (amount, to_account))
    return conn.execute(
        f"INSERT INTO transactions (id, idempotency_key, from_account, to_account, amount, currency, status, created_by) "
        f"VALUES (%s, %s, %s, %s, %s, %s, 'COMPLETED', %s) RETURNING {TX_COLUMNS}",
        (uuid4(), idempotency_key, from_account, to_account, amount, currency, created_by),
    ).fetchone()


@router.post("/transactions", response_model=TransactionOut, status_code=201)
def create_transaction(
    body: TransactionIn,
    response: Response,
    user: User = Depends(require_role("client", "canary", "operator")),
    idempotency_key: str | None = Header(None, max_length=64),
):
    """Virement fictif atomique. Rejouer la meme Idempotency-Key renvoie la transaction existante."""
    with db.transaction() as conn:
        # Verrou des deux comptes dans un ordre fixe (evite les deadlocks entre virements croises).
        accounts = {
            row["id"]: row
            for row in conn.execute(
                "SELECT id, owner, balance, currency FROM accounts WHERE id = ANY(%s) ORDER BY id FOR UPDATE",
                ([body.from_account, body.to_account],),
            ).fetchall()
        }
        src, dst = accounts.get(body.from_account), accounts.get(body.to_account)
        if not src or not dst:
            raise HTTPException(404, "Compte inconnu")
        if user.role == "client" and src["owner"] != user.sub:
            raise HTTPException(403, "Ce compte ne vous appartient pas")

        if idempotency_key:
            existing = conn.execute(
                f"SELECT {TX_COLUMNS} FROM transactions WHERE idempotency_key = %s", (idempotency_key,)
            ).fetchone()
            if existing:
                response.status_code = 200
                return existing

        if not (src["currency"] == dst["currency"] == body.currency):
            raise HTTPException(422, "Devise incompatible")
        if src["balance"] < body.amount:
            TRANSACTIONS.labels("rejected").inc()
            raise HTTPException(422, "Solde insuffisant")

        row = apply_transfer(conn, body.from_account, body.to_account, body.amount, body.currency, user.sub, idempotency_key)
    TRANSACTIONS.labels("completed").inc()
    return row


@router.get("/transactions/{tx_id}", response_model=TransactionOut)
def get_transaction(tx_id: str, user: User = Depends(require_role("client", "canary", "operator"))):
    with db.transaction() as conn:
        row = conn.execute(
            f"SELECT {TX_COLUMNS} FROM transactions WHERE id::text = %s", (tx_id,)
        ).fetchone()
    if not row or (user.role == "client" and row["created_by"] != user.sub):
        raise HTTPException(404, "Transaction introuvable")
    return row


@router.get("/transactions", response_model=list[TransactionOut])
def list_transactions(
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(require_role("client", "canary", "operator")),
):
    where, params = ("WHERE created_by = %s", (user.sub, limit)) if user.role == "client" else ("", (limit,))
    with db.transaction() as conn:
        return conn.execute(
            f"SELECT {TX_COLUMNS} FROM transactions {where} ORDER BY created_at DESC LIMIT %s", params
        ).fetchall()


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(user: User = Depends(require_role("client", "canary", "operator"))):
    """Comptes visibles : ceux du client connecté, tous pour les autres rôles. Sert à l'écran « mes comptes » du front."""
    where, params = ("WHERE owner = %s", (user.sub,)) if user.role == "client" else ("", ())
    with db.transaction() as conn:
        return conn.execute(
            f"SELECT id, owner, balance, currency FROM accounts {where} ORDER BY id", params
        ).fetchall()


@router.get("/accounts/{account_id}", response_model=AccountOut)
def get_account(account_id: str, user: User = Depends(require_role("client", "canary", "operator"))):
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT id, owner, balance, currency FROM accounts WHERE id = %s", (account_id,)
        ).fetchone()
    if not row or (user.role == "client" and row["owner"] != user.sub):
        raise HTTPException(404, "Compte introuvable")
    return row


@router.get("/ledger/check", response_model=LedgerCheck)
def ledger_check(user: User = Depends(require_role("canary", "operator"))):
    """Coherence comptable : solde = solde initial + credits - debits, pour chaque compte.
    Utilise par la verification de reprise pour detecter des donnees incoherentes."""
    with db.transaction() as conn:
        rows = conn.execute(
            """
            SELECT a.id FROM accounts a
            WHERE a.balance <> a.initial_balance
                + COALESCE((SELECT sum(amount) FROM transactions t WHERE t.to_account = a.id AND t.status = 'COMPLETED'), 0)
                - COALESCE((SELECT sum(amount) FROM transactions t WHERE t.from_account = a.id AND t.status = 'COMPLETED'), 0)
            """
        ).fetchall()
    ids = [r["id"] for r in rows]
    return {"consistent": not ids, "mismatches": ids}
