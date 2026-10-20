"""Comptes de démonstration. POC : pas de vraie base d'utilisateurs.

Le champ `sub` du jeton est le nom d'utilisateur : il doit être égal au `owner` des comptes dans l'API
(alice -> ACC-ALICE, bob -> ACC-BOB). Les mots de passe de démo sont fictifs et documentés dans dev/README.md.
"""
import json

from .config import secret, settings
from .passwords import hash_password


def load_users() -> dict[str, dict]:
    with open(settings.users_file, encoding="utf-8") as f:
        users = json.load(f)

    # Le canary (sonde de vérification) a un VRAI secret, jamais écrit dans le dépôt :
    # le compte n'existe que si son mot de passe est fourni (CANARY_PASSWORD_FILE).
    canary_password = secret("CANARY_PASSWORD")
    if canary_password:
        users["canary"] = {"role": "canary", "password_hash": hash_password(canary_password)}
    return users
