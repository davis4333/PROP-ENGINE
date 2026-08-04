"""API test fixtures. `client` wires FastAPI's `get_db` dependency to the
same transaction-per-test `db_session` the rest of the suite uses (see
tests/conftest.py), so requests see exactly the rows a test set up and
nothing commits to the real database."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from cassandra.api.deps import get_db
from cassandra.api.main import app


@pytest.fixture
def client(db_session) -> Generator[TestClient, None, None]:
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
