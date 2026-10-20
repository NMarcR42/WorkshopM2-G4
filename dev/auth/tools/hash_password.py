"""Fabrique le hash d'un mot de passe pour app/users.json.

  python tools/hash_password.py "mon-mot-de-passe"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.passwords import hash_password  # noqa: E402

print(hash_password(sys.argv[1]))
