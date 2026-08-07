"""GET /health -- Phase 2B: exposes the deployed git commit SHA so an
operator can confirm which code is actually running."""

from __future__ import annotations

from cassandra.api import main


def test_health_returns_ok_status(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_includes_the_resolved_git_commit_sha(client, monkeypatch):
    monkeypatch.setattr(main, "get_git_commit_sha", lambda: "abc123deadbeef")
    response = client.get("/health")
    assert response.json()["git_commit_sha"] == "abc123deadbeef"


def test_health_reports_none_rather_than_erroring_when_sha_unavailable(client, monkeypatch):
    monkeypatch.setattr(main, "get_git_commit_sha", lambda: None)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["git_commit_sha"] is None
