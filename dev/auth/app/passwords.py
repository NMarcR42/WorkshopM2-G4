"""Hash de mots de passe avec la bibliothèque standard (PBKDF2), pour éviter une dépendance de plus.

Format stocké : pbkdf2_sha256$<itérations>$<sel hex>$<hash hex>
"""
import hashlib
import hmac
import os

# Assez lent pour freiner un brute-force, assez rapide pour ne pas saturer le CPU à chaque login.
ITERATIONS = 100_000


def _derive(password: str, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations).hex()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${_derive(password, salt, ITERATIONS)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt_hex, expected = stored.split("$")
        candidate = _derive(password, bytes.fromhex(salt_hex), int(iterations))
    except ValueError:
        return False
    # compare_digest : temps constant, pour ne pas révéler combien de caractères sont corrects.
    return hmac.compare_digest(candidate, expected)


# Hash factice vérifié quand l'utilisateur n'existe pas : le temps de réponse est le même
# qu'un mauvais mot de passe, on ne révèle pas quels identifiants existent.
DUMMY_HASH = hash_password("jamais-utilise")
