import os

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-not-a-real-one")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:  # le "with" lance le lifespan (chargement des comptes)
        yield c
