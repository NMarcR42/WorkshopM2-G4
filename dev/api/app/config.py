import os
from dataclasses import dataclass
from pathlib import Path


def secret(name: str, default: str | None = None) -> str | None:
    """Lit un secret depuis NAME_FILE (Docker secret) sinon NAME (dev local uniquement)."""
    path = os.getenv(f"{name}_FILE")
    if path:
        return Path(path).read_text().strip()
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    db_host: str = os.getenv("DB_HOST", "localhost")
    db_port: int = int(os.getenv("DB_PORT", "5432"))
    db_name: str = os.getenv("DB_NAME", "payments")
    db_user: str = os.getenv("DB_USER", "payments")
    db_pool_max: int = int(os.getenv("DB_POOL_MAX", "10"))
    db_pool_timeout_s: float = float(os.getenv("DB_POOL_TIMEOUT_S", "3"))

    # --- Transaction de contrôle (preuve de reprise officielle de l'infra)
    # Pas de valeur par défaut : une mauvaise cible silencieuse donnerait une fausse preuve (même règle que le canary).
    auth_url: str = os.getenv("AUTH_URL", "").rstrip("/")
    synthetic_timeout_s: float = float(os.getenv("SYNTHETIC_TIMEOUT_S", "2"))
    # Comptes dédiés : les soldes des vrais clients ne bougent jamais.
    synthetic_accounts: tuple = tuple(os.getenv("SYNTHETIC_ACCOUNTS", "ACC-CANARY-A,ACC-CANARY-B").split(","))

    @property
    def db_password(self) -> str:
        return secret("DB_PASSWORD", "") or ""

    @property
    def synthetic_probe_token(self) -> str | None:
        return secret("SYNTHETIC_PROBE_TOKEN")

    @property
    def jwt_secret(self) -> str:
        value = secret("JWT_SECRET")
        if not value:
            raise RuntimeError("JWT_SECRET(_FILE) manquant")
        return value


settings = Settings()
