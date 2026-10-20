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
    canary_url: str = os.getenv("CANARY_URL", "").rstrip("/")
    remediation_url: str = os.getenv("ENGINE_URL", "").rstrip("/")
    prometheus_url: str = os.getenv("PROMETHEUS_URL", "").rstrip("/")
    # Sources de l'infra (voir doc/CONTRATS-INTERFACES.md). Vides = source désactivée : la page s'affiche sans.
    # Mono-hôte : noms de services Docker (posés par le compose) ; vm-ops : adresses réelles par .env.
    alertmanager_url: str = os.getenv("ALERTMANAGER_URL", "").rstrip("/")
    loki_url: str = os.getenv("LOKI_URL", "").rstrip("/")
    # Étiquette Loki des journaux de remédiation, au format clé=valeur (service=remediation, syslog_identifier=ra-remediate).
    # Fixée par la configuration, jamais par le navigateur : sinon n'importe quel visiteur interrogerait tous les logs.
    loki_remediation_label: str = os.getenv("LOKI_REMEDIATION_LABEL", "")
    # Dossier du site compilé (image Docker). Absent en dev : le site est alors servi par Vite.
    static_dir: str = os.getenv("STATIC_DIR", "/srv/static")
    timeout_s: float = float(os.getenv("UPSTREAM_TIMEOUT_S", "3"))
    # Service de lecture : une sonde considérée « périmée » au-delà de ce délai n'est plus une preuve d'état sain.
    probe_stale_s: float = float(os.getenv("PROBE_STALE_S", "20"))

    @property
    def engine_token(self) -> str | None:
        # Le token reste côté serveur : le navigateur ne le voit jamais, il ne parle qu'à ce service (lecture seule).
        return secret("ENGINE_TOKEN")


settings = Settings()
