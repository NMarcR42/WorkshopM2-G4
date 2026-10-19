"""Acces PostgreSQL : pool de connexions, schema, donnees de demonstration.

L'API demarre meme si la base est indisponible et se rebranche toute seule :
le schema est cree a la premiere connexion reussie.
"""
import threading
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id              TEXT PRIMARY KEY,
    owner           TEXT NOT NULL,
    initial_balance NUMERIC(14,2) NOT NULL,
    balance         NUMERIC(14,2) NOT NULL CHECK (balance >= 0),
    currency        CHAR(3) NOT NULL DEFAULT 'EUR'
);
CREATE TABLE IF NOT EXISTS transactions (
    id              UUID PRIMARY KEY,
    idempotency_key TEXT UNIQUE,
    from_account    TEXT NOT NULL REFERENCES accounts(id),
    to_account      TEXT NOT NULL REFERENCES accounts(id),
    amount          NUMERIC(14,2) NOT NULL CHECK (amount > 0),
    currency        CHAR(3) NOT NULL,
    status          TEXT NOT NULL,
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS transactions_created_at ON transactions (created_at DESC);
"""

# Donnees 100 % fictives. 'canary' = comptes utilises par la sonde de verification.
SEED = [
    ("ACC-ALICE", "alice", 1000),
    ("ACC-BOB", "bob", 500),
    ("ACC-MERCHANT", "merchant", 0),
    ("ACC-CANARY-A", "canary", 1_000_000),
    ("ACC-CANARY-B", "canary", 0),
]

pool = ConnectionPool(
    conninfo="",  # renseigne dans open()
    min_size=1,
    max_size=settings.db_pool_max,
    timeout=settings.db_pool_timeout_s,
    open=False,
    kwargs={"row_factory": dict_row},
)
_schema_ready = False
_lock = threading.Lock()


def open_pool() -> None:
    pool.conninfo = (
        f"host={settings.db_host} port={settings.db_port} dbname={settings.db_name} "
        f"user={settings.db_user} password={settings.db_password} connect_timeout=3"
    )
    pool.open(wait=False)


def close_pool() -> None:
    pool.close()


def _ensure_schema(conn) -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _lock:
        if _schema_ready:
            return
        conn.execute("SELECT pg_advisory_xact_lock(748210)")  # plusieurs replicas : un seul cree
        conn.execute(SCHEMA)
        for acc_id, owner, balance in SEED:
            conn.execute(
                "INSERT INTO accounts (id, owner, initial_balance, balance) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (id) DO NOTHING",
                (acc_id, owner, balance, balance),
            )
        conn.commit()
        _schema_ready = True


@contextmanager
def transaction():
    """Une transaction SQL : commit a la sortie normale, rollback sur exception."""
    with pool.connection() as conn:
        _ensure_schema(conn)
        yield conn


def ping() -> bool:
    try:
        with pool.connection(timeout=1) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False

