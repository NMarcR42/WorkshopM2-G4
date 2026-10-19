"""Fabrique un JWT de test (dev local uniquement ; en vrai, c'est le service auth qui les emet).

  JWT_SECRET=... python tools/make_token.py alice client
  JWT_SECRET_FILE=../../.secrets/jwt_secret python tools/make_token.py canary canary
"""
import os
import sys
import time
from pathlib import Path

import jwt

secret_file = os.getenv("JWT_SECRET_FILE")
secret = Path(secret_file).read_text().strip() if secret_file else os.environ["JWT_SECRET"]
sub, role = sys.argv[1], sys.argv[2]
print(jwt.encode({"sub": sub, "role": role, "exp": int(time.time()) + 3600}, secret, algorithm="HS256"))
