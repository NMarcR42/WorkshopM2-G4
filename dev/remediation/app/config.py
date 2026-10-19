import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path


def secret(name: str, default: str | None = None) -> str | None:
    """Lit un secret depuis NAME_FILE (Docker secret) sinon NAME (dev local uniquement)."""
    path = os.getenv(f"{name}_FILE")
    if path:
        return Path(path).read_text().strip()
    return os.getenv(name, default)


def _networks(raw: str) -> tuple:
    return tuple(ipaddress.ip_network(p.strip()) for p in raw.split(",") if p.strip())


@dataclass(frozen=True)
class Settings:
    # local = docker-proxy (restart uniquement) ; ssh = Ansible. Même interface, seul l'executor change.
    mode: str = os.getenv("REMEDIATION_MODE", "local")
    canary_url: str = os.getenv("CANARY_URL", "").rstrip("/")
    incidents_dir: str = os.getenv("INCIDENTS_DIR", "/var/lib/resilience/incidents")

    # --- Vérification de reprise : on attend que le canary passe, mais pas indéfiniment.
    verify_timeout_s: float = float(os.getenv("VERIFY_TIMEOUT_S", "30"))
    verify_interval_s: float = float(os.getenv("VERIFY_INTERVAL_S", "3"))
    # Le détecteur continue de signaler pendant la réparation : sans délai de grâce, on réagirait en boucle à la même attaque.
    cooldown_s: float = float(os.getenv("REMEDIATION_COOLDOWN_S", "30"))

    # --- Blocage d'IP. Politique de réponse (pas de la détection : celle-ci reste au ML).
    block_min_share: float = float(os.getenv("BLOCK_MIN_SHARE", "0.5"))   # part du trafic au-delà de laquelle une IP est bloquée
    block_ttl_s: int = int(os.getenv("BLOCK_TTL_S", "900"))
    max_block_ips: int = int(os.getenv("MAX_BLOCK_IPS", "20"))            # un signal falsifié ne peut pas bloquer tout le monde
    # Jamais bloquer ces réseaux (sonde canary, réseaux Docker, boucle locale) : on couperait notre propre preuve de reprise.
    protected_cidrs: tuple = _networks(os.getenv("PROTECTED_CIDRS", ""))

    # --- Executor local (docker-proxy)
    docker_host: str = os.getenv("DOCKER_HOST", "tcp://docker-proxy:2375")
    # Le proxy interdit de lister les conteneurs : on les désigne par nom. {service} = nom du service du compose.
    container_template: str = os.getenv("CONTAINER_NAME_TEMPLATE", "resilience-{service}-1")
    waf_service: str = os.getenv("WAF_SERVICE", "waf")
    blocklist_file: str = os.getenv("BLOCKLIST_FILE", "/etc/waf/blocklist/blocklist.txt")

    # --- Executor ssh (Ansible)
    ansible_inventory: str = os.getenv("ANSIBLE_INVENTORY", "")
    ansible_playbooks: str = os.getenv("ANSIBLE_PLAYBOOKS_DIR", "/ansible/playbooks")
    action_timeout_s: float = float(os.getenv("ACTION_TIMEOUT_S", "60"))

    @property
    def engine_token(self) -> str:
        value = secret("ENGINE_TOKEN")
        if not value:
            raise RuntimeError("ENGINE_TOKEN(_FILE) manquant")
        return value


settings = Settings()
