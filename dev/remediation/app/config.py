import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path


def secret(name: str, default: str | None = None, default_file: str | None = None) -> str | None:
    """Lit un secret depuis NAME_FILE (Docker secret), sinon default_file s'il existe, sinon NAME (dev local uniquement)."""
    path = os.getenv(f"{name}_FILE") or (default_file if default_file and Path(default_file).is_file() else None)
    if path:
        return Path(path).read_text().strip()
    return os.getenv(name, default)


def _networks(raw: str) -> tuple:
    return tuple(ipaddress.ip_network(p.strip()) for p in raw.split(",") if p.strip())


@dataclass(frozen=True)
class Settings:
    # ansible (VM-OPS, défaut) ; local = docker-proxy pour tester la logique sans Ansible. « ssh » reste un alias
    # d'« ansible » : les fichiers compose existants le posent. Même interface, seul l'executor change.
    mode: str = os.getenv("REMEDIATION_MODE", "ansible")
    canary_url: str = os.getenv("CANARY_URL", "").rstrip("/")
    incidents_dir: str = os.getenv("INCIDENTS_DIR", "/var/lib/resilience/incidents")

    # --- Vérification de reprise : on attend que le canary passe, mais pas indéfiniment.
    verify_timeout_s: float = float(os.getenv("VERIFY_TIMEOUT_S", "30"))
    verify_interval_s: float = float(os.getenv("VERIFY_INTERVAL_S", "3"))
    # Le détecteur continue de signaler pendant la réparation : sans délai de grâce, on réagirait en boucle à la même attaque.
    cooldown_s: float = float(os.getenv("REMEDIATION_COOLDOWN_S", "30"))
    # Anti-rebond par (action, cible) : Alertmanager répète une alerte tant qu'elle brûle, on ne relance pas la même
    # action pendant qu'elle agit ou vient d'agir.
    action_cooldown_s: float = float(os.getenv("ACTION_COOLDOWN_S", "90"))
    # Une alerte « auto » (décision confiée au moteur) est d'abord confrontée au canary : service sain = faux positif probable.
    auto_verify_first: bool = os.getenv("AUTO_VERIFY_FIRST", "1") == "1"
    # Liste fermée : le label service vient d'une alerte, il ne doit jamais désigner autre chose que nos services.
    allowed_services: tuple = tuple(x.strip() for x in os.getenv("ALLOWED_SERVICES", "api,auth,frontend").split(",") if x.strip())

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

    action_timeout_s: float = float(os.getenv("ACTION_TIMEOUT_S", "60"))

    # --- Executor ansible : dépôt ansible/ monté en lecture seule, playbooks dans <workdir>/<subdir>/<action>.yml
    ansible_workdir: str = os.getenv("ANSIBLE_WORKDIR", "/work")
    ansible_playbooks_subdir: str = os.getenv("ANSIBLE_PLAYBOOKS_SUBDIR", "remediation")
    ansible_inventory: str = os.getenv("ANSIBLE_INVENTORY", "")   # vide : l'ansible.cfg du dépôt fait foi
    # Un restore_db ou un rollback_vm est bien plus long qu'un restart : timeout dédié.
    ansible_timeout_s: float = float(os.getenv("ANSIBLE_TIMEOUT_S", "600"))
    ansible_success_marker: str = os.getenv("ANSIBLE_SUCCESS_MARKER", "SERVICE RÉTABLI")

    @property
    def alert_token(self) -> str:
        """Jeton du webhook Alertmanager (secret fourni par l'infra)."""
        value = secret("ALERT_WEBHOOK_TOKEN", default_file="/run/secrets/alert_webhook_token")
        if not value:
            raise RuntimeError("alert_webhook_token manquant (ALERT_WEBHOOK_TOKEN_FILE ou /run/secrets/alert_webhook_token)")
        return value

    @property
    def engine_token(self) -> str:
        """Jeton de lecture des incidents (dashboard). Sans secret dédié, on réutilise celui du webhook : sur la VM,
        l'infra ne fournit que alert_webhook_token."""
        return secret("ENGINE_TOKEN") or self.alert_token


settings = Settings()
