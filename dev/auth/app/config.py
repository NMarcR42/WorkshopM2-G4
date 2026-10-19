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
    # Durée de vie du jeton. Courte : un jeton volé expire vite (le front redemande un login).
    token_ttl_s: int = int(os.getenv("AUTH_TOKEN_TTL_S", "1800"))
    # Comptes de démonstration (hash de mots de passe fictifs, pas de secret).
    users_file: str = os.getenv("AUTH_USERS_FILE", str(Path(__file__).parent / "users.json"))

    @property
    def jwt_secret(self) -> str:
        # Même secret que l'API : c'est lui qui permet à l'API de vérifier nos jetons sans nous appeler.
        value = secret("JWT_SECRET")
        if not value:
            raise RuntimeError("JWT_SECRET(_FILE) manquant")
        return value


settings = Settings()
