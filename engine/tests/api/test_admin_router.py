"""GET /api/admin/status and POST /api/admin/runs/{slate_date}/{run,grade}
-- ADR 0011's shared-secret gate, and that admin surfaces source health /
pipeline runs correctly. The `run`/`grade` actions' actual pipeline
behavior is covered by tests/integration/test_run_slate.py; these tests
only check the API wiring (auth, status codes, response shape)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert

from cassandra.config import settings
from cassandra.db.models.pipeline import PipelineRun, PipelineRunStage
from cassandra.db.models.sources import Source, SourceHealth

AUTH = {"X-Admin-Secret": settings.admin_shared_secret}


def test_admin_status_requires_auth(client):
    response = client.get("/api/admin/status")
    assert response.status_code == 401


def test_admin_status_rejects_wrong_secret(client):
    response = client.get("/api/admin/status", headers={"X-Admin-Secret": "wrong"})
    assert response.status_code == 401


def test_admin_status_with_correct_secret_returns_versions_and_empty_state(client):
    response = client.get("/api/admin/status", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["model_version"] == "k-model-0.1.0"
    assert body["decision_policy_version"] == "k-decision-0.1.0"
    assert body["sources"] == []
    assert body["recent_runs"] == []
    assert body["blocking_issues"] == []


def test_admin_status_surfaces_source_health_and_failed_run_as_blocking(client, db_session):
    stmt = pg_insert(Source).values(source_id="src-admin-test", name="src-admin-test", kind="lines")
    db_session.execute(stmt)
    db_session.add(
        SourceHealth(
            source_id="src-admin-test",
            last_status="unavailable",
            last_failure_at=datetime.now(UTC),
            consecutive_failures=5,
        )
    )
    db_session.add(
        PipelineRun(run_id="run-admin-failed", slate_date=datetime.now(UTC).date(), status="failed")
    )
    db_session.add(
        PipelineRunStage(run_id="run-admin-failed", stage="INGEST", status="failed", detail="boom")
    )
    db_session.flush()

    response = client.get("/api/admin/status", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert any(s["source_id"] == "src-admin-test" and s["consecutive_failures"] == 5 for s in body["sources"])
    assert any(r["run_id"] == "run-admin-failed" and r["status"] == "failed" for r in body["recent_runs"])
    assert any("run-admin-failed" in issue for issue in body["blocking_issues"])
    assert any("src-admin-test" in issue for issue in body["blocking_issues"])


def test_admin_run_actions_require_auth(client):
    assert client.post("/api/admin/runs/2023-06-15/run").status_code == 401
    assert client.post("/api/admin/runs/2023-06-15/grade").status_code == 401
