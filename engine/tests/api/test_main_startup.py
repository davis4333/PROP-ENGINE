"""main.py's lifespan startup gate: a production deployment must refuse
to start at all on a weak/placeholder admin secret (Phase 8's security
requirement). Uses `with TestClient(app) as client:` deliberately --
that's the one form that actually runs FastAPI's lifespan (see
tests/api/conftest.py's `client` fixture docstring, which uses the
non-context-manager form specifically to skip it for every other test).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cassandra.api.main import app
from cassandra.config import settings


def test_production_with_weak_secret_refuses_to_start(monkeypatch):
    monkeypatch.setattr(settings, "production_mode", True)
    monkeypatch.setattr(settings, "admin_shared_secret", "test")
    with pytest.raises(RuntimeError, match="Refusing to start"), TestClient(app):
        pass


def test_production_with_strong_secret_starts_normally(monkeypatch):
    monkeypatch.setattr(settings, "production_mode", True)
    monkeypatch.setattr(settings, "admin_shared_secret", "f3a9c1e7b2d84a6f9e0c1b3d5a7f9e1c3b5d7f9a")
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200


def test_non_production_with_weak_secret_still_starts(monkeypatch):
    # Local/dev/CI must never be blocked by this -- ADR 0011's demo-only
    # secret is expected there.
    monkeypatch.setattr(settings, "production_mode", False)
    monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)
    monkeypatch.setattr(settings, "admin_shared_secret", "change-me-dev-only")
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
