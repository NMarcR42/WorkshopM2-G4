import os
import time

import jwt
import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-not-a-real-one")
os.environ.setdefault("DB_PASSWORD", "test")
# Tests avec base : lancer un Postgres et definir TEST_DB_HOST (la CI le fait).
if os.getenv("TEST_DB_HOST"):
    os.environ["DB_HOST"] = os.environ["TEST_DB_HOST"]
    os.environ["DB_PORT"] = os.getenv("TEST_DB_PORT", "5432")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

needs_db = pytest.mark.skipif(not os.getenv("TEST_DB_HOST"), reason="TEST_DB_HOST non defini")


def token(sub: str, role: str, ttl: int = 3600) -> dict:
    jwt_ = jwt.encode({"sub": sub, "role": role, "exp": int(time.time()) + ttl},
                      os.environ["JWT_SECRET"], algorithm="HS256")
    return {"Authorization": f"Bearer {jwt_}"}


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
