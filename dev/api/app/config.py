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

    @property
    def db_password(self) -> str:
        return secret("DB_PASSWORD", "") or ""

    @property
    def jwt_secret(self) -> str:
        value = secret("JWT_SECRET")
        if not value:
            raise RuntimeError("JWT_SECRET(_FILE) manquant")
        return value


settings = Settings()
