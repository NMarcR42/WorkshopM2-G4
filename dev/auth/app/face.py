"""Lien avec le service de reconnaissance faciale (PC hôte, voir ia/README-face.md).

Pourquoi /auth/confirm : c'est le seul moyen prévu par le contrat IA de valider un token visage côté serveur.
Il est à usage unique et lié à l'utilisateur, donc un token volé ou rejoué pour un autre compte est refusé.
Appel de serveur à serveur protégé par une clé de service, jamais depuis le navigateur.
"""
import json
import urllib.error
import urllib.request

from .config import settings


class FaceRejected(Exception):
    """Le service IA a répondu que le token visage est absent, expiré ou déjà utilisé."""


class FaceUnavailable(Exception):
    """Le service IA est injoignable ou mal configuré : on refuse proprement (fail closed)."""


def confirm(username: str, token: str, ok: bool) -> None:
    """Valide (et consomme) le token ; `ok` = résultat de notre vérification du mot de passe (pilote la LED)."""
    if not settings.face_service_url or not settings.face_service_key:
        raise FaceUnavailable("FACE_SERVICE_URL ou clé de service non configurés")
    req = urllib.request.Request(
        settings.face_service_url.rstrip("/") + "/auth/confirm",
        data=json.dumps({"user": username, "token": token, "ok": ok}).encode(),
        headers={"Content-Type": "application/json", "X-Service-Key": settings.face_service_key},
        method="POST",
    )
    try:
        # Délai court : un service IA bloqué ne doit pas bloquer tous les logins.
        with urllib.request.urlopen(req, timeout=settings.face_timeout_s):
            return
    except urllib.error.HTTPError as e:
        # 403 = token invalide/expiré (ou clé de service fausse, indiscernable ici) ; le reste = panne.
        if e.code == 403:
            raise FaceRejected() from e
        raise FaceUnavailable(f"service IA : HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise FaceUnavailable(f"service IA injoignable : {e}") from e
