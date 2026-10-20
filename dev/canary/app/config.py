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
    # Adresse du WAF : le canary doit passer par la même porte que les vrais clients,
    # sinon il ne prouverait pas que le chemin client fonctionne. Aucune valeur par défaut :
    # une mauvaise cible silencieuse donnerait une fausse preuve.
    waf_url: str = os.getenv("WAF_URL", "").rstrip("/")
    api_prefix: str = os.getenv("CANARY_API_PREFIX", "/api")
    auth_prefix: str = os.getenv("CANARY_AUTH_PREFIX", "/auth")
    interval_s: float = float(os.getenv("CANARY_INTERVAL_S", "5"))
    # Plus court que l'intervalle de remédiation : un service qui répond en 30 s est déjà en panne pour un client.
    timeout_s: float = float(os.getenv("CANARY_TIMEOUT_S", "4"))
    username: str = os.getenv("CANARY_USERNAME", "canary")
    # Comptes et montant dédiés à la sonde (créés par l'API au démarrage) : les soldes des vrais clients ne bougent jamais.
    from_account: str = os.getenv("CANARY_FROM_ACCOUNT", "ACC-CANARY-A")
    to_account: str = os.getenv("CANARY_TO_ACCOUNT", "ACC-CANARY-B")
    amount: str = os.getenv("CANARY_AMOUNT", "0.01")
    currency: str = os.getenv("CANARY_CURRENCY", "EUR")


settings = Settings()
