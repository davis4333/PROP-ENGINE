"""GET /api/admin/status and POST /api/admin/runs/{slate_date}/{run,grade}
-- ADR 0011's shared-secret gate, and that admin surfaces source health /
pipeline runs correctly. The `run`/`grade` actions' actual pipeline
behavior is covered by tests/integration/test_run_slate.py; these tests
only check the API wiring (auth, status codes, response shape).

Also covers POST /api/admin/lines/{slate_date}/{preview,import} -- the
matching/duplicate-detection/leakage-safety behavior itself is covered by
tests/integration/test_manual_line_import.py; these tests only check the
API wiring on top of it."""

from __future__ import annotations

from datetime import UTC, datetime, time
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert as pg_insert

from cassandra.api import deps
from cassandra.api.routers import admin as admin_router
from cassandra.config import settings
from cassandra.db.models.grading import Grade
from cassandra.db.models.identity import Game, Player
from cassandra.db.models.pipeline import PipelineRun, PipelineRunStage
from cassandra.db.models.raw import RawProbablePitcher
from cassandra.db.models.sources import Source, SourceHealth
from cassandra.registry.service import create_model_artifact, promote_to_active, register_as_candidate

from ._helpers import publish

AUTH = {"X-Admin-Secret": settings.admin_shared_secret}


def test_admin_status_requires_auth(client):
    response = client.get("/api/admin/status")
    assert response.status_code == 401


def test_admin_status_rejects_wrong_secret(client):
    response = client.get("/api/admin/status", headers={"X-Admin-Secret": "wrong"})
    assert response.status_code == 401


def test_failed_admin_auth_is_logged_without_the_attempted_secret(client, caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="cassandra.api.deps"):
        client.get("/api/admin/status", headers={"X-Admin-Secret": "a-guessed-secret-value"})

    messages = [r.getMessage() for r in caplog.records]
    assert any("admin auth failed" in m for m in messages)
    assert not any("a-guessed-secret-value" in m for m in messages)


def test_admin_status_with_correct_secret_returns_versions_and_empty_state(client, monkeypatch):
    monkeypatch.setattr(admin_router, "get_git_commit_sha", lambda: "deadbeef1234")
    response = client.get("/api/admin/status", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["model_version"] == "k-model-0.1.0"
    assert body["decision_policy_version"] == "k-decision-0.2.0"
    assert body["sources"] == []
    assert body["recent_runs"] == []
    assert body["git_commit_sha"] == "deadbeef1234"
    assert body["blocking_issues"] == []


def test_admin_status_warns_when_git_commit_sha_is_unavailable(client, monkeypatch):
    # Phase 2B: a missing deployed commit SHA (e.g. GIT_COMMIT_SHA unset
    # and no .git directory to introspect, the expected Replit case) must
    # be a visible warning, never a silent gap.
    monkeypatch.setattr(admin_router, "get_git_commit_sha", lambda: None)
    response = client.get("/api/admin/status", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["git_commit_sha"] is None
    assert any("git commit sha" in issue.lower() for issue in body["blocking_issues"])


def test_admin_status_surfaces_source_health_and_failed_run_as_blocking(client, db_session):
    stmt = pg_insert(Source).values(source_id="src-admin-test", name="src-admin-test", kind="lines")
    db_session.execute(stmt)
    db_session.add(
        SourceHealth(
            source_id="src-admin-test",
            last_status="FAILED",
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


def test_umpire_stub_never_appears_as_a_blocking_issue(client, db_session):
    # umpire_stub is a permanent stand-in (no free umpire source exists)
    # and always reports unavailable by design -- the handbook is
    # explicit this must never block or alarm anything (CLAUDE.md,
    # CURRENT_STATE_AUDIT.md's Provisional section). Regression for a
    # real bug found live: it showed up under "Blocking Issues" forever
    # since nothing could ever bring its consecutive-failure count down.
    # last_status="DISABLED" (not the generic "unavailable"/"FAILED") is
    # exactly what UmpireStubAdapter's unavailable_reason="disabled" now
    # produces via ingest_service.py's _source_health_status() -- see
    # NEVER_BLOCKING_STATES in api/routers/admin.py, which is keyed on
    # this state, not the source's name.
    # umpire_stub is also the real, permanent canonical source name a live
    # ingestion run creates -- on_conflict_do_nothing (matching line 181's
    # pattern below) avoids a UniqueViolation if this test runs against a
    # dev DB that's already been seeded/run for real (found via this
    # session's test-coverage audit).
    stmt = pg_insert(Source).values(source_id="umpire_stub", name="umpire_stub", kind="umpire")
    db_session.execute(stmt.on_conflict_do_nothing(index_elements=[Source.source_id]))
    # source_health is keyed on source_id too and is a real, permanent row
    # once any live ingestion has run -- merge() (upsert by primary key)
    # instead of add() for the same reason as the on_conflict_do_nothing
    # above.
    db_session.merge(
        SourceHealth(
            source_id="umpire_stub",
            last_status="DISABLED",
            last_failure_at=datetime.now(UTC),
            consecutive_failures=999,
        )
    )
    db_session.flush()

    response = client.get("/api/admin/status", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    # still visible in source health (transparency) --
    assert any(s["source_id"] == "umpire_stub" for s in body["sources"])
    # -- just never escalated to a blocking issue
    assert not any("umpire_stub" in issue for issue in body["blocking_issues"])


def test_admin_run_actions_require_auth(client):
    assert client.post("/api/admin/runs/2023-06-15/run").status_code == 401
    assert client.post("/api/admin/runs/2023-06-15/grade").status_code == 401


def test_repeated_wrong_secrets_get_locked_out(client, monkeypatch):
    # Regression for a real security-review finding: the admin gate had
    # no rate limiting at all, making a weak/guessable secret an
    # unbounded brute-force target once genuinely publicly reachable.
    monkeypatch.setattr(deps, "_failures_by_client", {})
    for _ in range(deps._FAILURE_LIMIT):
        response = client.get("/api/admin/status", headers={"X-Admin-Secret": "wrong"})
        assert response.status_code == 401

    locked_out = client.get("/api/admin/status", headers={"X-Admin-Secret": "wrong"})
    assert locked_out.status_code == 429

    # Even the CORRECT secret is rejected during lockout -- the whole
    # point is to slow down a brute-force attempt regardless of whether
    # the attacker's next guess happens to be right.
    still_locked = client.get("/api/admin/status", headers=AUTH)
    assert still_locked.status_code == 429


def test_correct_secret_never_counts_as_a_failure(client, monkeypatch):
    monkeypatch.setattr(deps, "_failures_by_client", {})
    for _ in range(deps._FAILURE_LIMIT + 5):
        response = client.get("/api/admin/status", headers=AUTH)
        assert response.status_code == 200


MANUAL_LINE_SLATE_DATE = "2023-06-15"
MANUAL_LINE_GAME_PK = 900040001
MANUAL_LINE_PITCHER_MLB_ID = 900041001


def _seed_manual_line_slate(db_session) -> None:
    stmt = pg_insert(Source).values(
        source_id="test-admin-lines-source", name="test-admin-lines-source", kind="lines"
    )
    db_session.execute(stmt.on_conflict_do_nothing(index_elements=[Source.source_id]))
    db_session.add(
        Game(
            game_id=f"test-admin-lines-game-{MANUAL_LINE_GAME_PK}",
            mlb_game_pk=MANUAL_LINE_GAME_PK,
            game_date=datetime(2023, 6, 15),
            # 23:00 UTC is still 2023-06-15 in US/Eastern -- see
            # test_manual_line_import.py's _seed_game for why this
            # matters (config.slate_date_for()'s conversion, ADR 0009).
            scheduled_start_utc=datetime.combine(datetime(2023, 6, 15).date(), time(23, 0), tzinfo=UTC),
            status="Preview",
        )
    )
    db_session.add(
        RawProbablePitcher(
            source_id="test-admin-lines-source",
            mlb_game_pk=MANUAL_LINE_GAME_PK,
            player_mlb_id=MANUAL_LINE_PITCHER_MLB_ID,
            is_confirmed=True,
            observed_at=datetime.now(UTC),
            payload={},
        )
    )
    db_session.add(
        Player(
            player_id=f"test-admin-lines-player-{MANUAL_LINE_PITCHER_MLB_ID}",
            mlb_person_id=MANUAL_LINE_PITCHER_MLB_ID,
            full_name="Admin Test Pitcher",
        )
    )
    db_session.flush()


def test_lines_preview_requires_auth(client):
    response = client.post(f"/api/admin/lines/{MANUAL_LINE_SLATE_DATE}/preview", json={"entries": []})
    assert response.status_code == 401


def test_lines_import_requires_auth(client):
    response = client.post(f"/api/admin/lines/{MANUAL_LINE_SLATE_DATE}/import", json={"entries": []})
    assert response.status_code == 401


def test_lines_preview_matches_a_real_confirmed_starter(client, db_session):
    _seed_manual_line_slate(db_session)

    response = client.post(
        f"/api/admin/lines/{MANUAL_LINE_SLATE_DATE}/preview",
        headers=AUTH,
        json={"entries": [{"player_name": "Admin Test Pitcher", "line": 5.5, "over_price": -110}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["matched"]) == 1
    assert body["matched"][0]["player_mlb_id"] == MANUAL_LINE_PITCHER_MLB_ID
    assert body["matched"][0]["mlb_game_pk"] == MANUAL_LINE_GAME_PK
    assert body["unmatched"] == []


def test_lines_preview_rejects_an_absurd_line_value(client, db_session):
    # Regression for a real security-review finding: an unbounded line
    # reaches PoissonStrikeoutDistribution.cdf()'s O(k) loop
    # (decision/engine.py's `math.floor(line)`) -- a fat-fingered/
    # malicious extreme value should be rejected cleanly at the schema
    # boundary (422), not silently accepted and only caught deep in the
    # math.
    _seed_manual_line_slate(db_session)

    response = client.post(
        f"/api/admin/lines/{MANUAL_LINE_SLATE_DATE}/preview",
        headers=AUTH,
        json={"entries": [{"player_name": "Admin Test Pitcher", "line": 10_000_000.0}]},
    )

    assert response.status_code == 422


def test_lines_preview_reports_unmatched_entries(client, db_session):
    _seed_manual_line_slate(db_session)

    response = client.post(
        f"/api/admin/lines/{MANUAL_LINE_SLATE_DATE}/preview",
        headers=AUTH,
        json={"entries": [{"player_name": "Nobody Real", "line": 4.5}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matched"] == []
    assert len(body["unmatched"]) == 1
    assert "No confirmed starter" in body["unmatched"][0]["reason"]


def test_lines_import_writes_matched_entries_and_reports_unmatched(client, db_session):
    _seed_manual_line_slate(db_session)

    response = client.post(
        f"/api/admin/lines/{MANUAL_LINE_SLATE_DATE}/import",
        headers=AUTH,
        json={
            "entries": [
                {"player_name": "Admin Test Pitcher", "line": 5.5},
                {"player_name": "Nobody Real", "line": 4.5},
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["records_written"] == 1
    assert len(body["not_imported"]) == 1
    assert "Nobody Real" in body["not_imported"][0]


def test_admin_status_active_model_is_null_when_nothing_is_promoted(client, monkeypatch):
    monkeypatch.setattr(admin_router, "get_git_commit_sha", lambda: "deadbeef1234")
    response = client.get("/api/admin/status", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["active_model"] is None
    assert body["model_version"] == "k-model-0.1.0"  # falls back to the permanent baseline


def test_admin_status_surfaces_the_active_model_when_one_is_promoted(client, db_session, monkeypatch):
    monkeypatch.setattr(admin_router, "get_git_commit_sha", lambda: "deadbeef1234")
    artifact = create_model_artifact(
        db_session,
        model_family="poisson-regression",
        model_code_version="poisson-regression-challenger-0.1.0",
        coefficients=[0.5, 0.1, 2.0, -0.02, 0.0],
        coefficient_order=[
            "intercept",
            "log1p_expected_bf",
            "recent_k_rate",
            "rest_days",
            "rest_days_missing",
        ],
        preprocessing_rules={},
        training_dataset_id="ds_admin_test",
        dataset_builder_version="v1",
        availability_policy_version="v1",
        feature_set_version="v1",
        training_seasons=[2023],
        training_game_types=["R"],
        training_row_count=500,
        trained_at=datetime(2026, 8, 1, tzinfo=UTC),
        dependency_versions={},
        training_metrics={
            "mae": 1.5,
            "rmse": 1.9,
            "walk_forward_aggregate_baseline_mae": 2.1,
            "walk_forward_aggregate_challenger_mae": 1.7,
        },
        evaluation_report_ids=[],
        created_by="tester",
    )
    register_as_candidate(db_session, artifact_id=artifact.artifact_id, operator="tester")
    promote_to_active(db_session, artifact_id=artifact.artifact_id, operator="tester", reason="admin test")
    db_session.flush()

    response = client.get("/api/admin/status", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["model_version"] == artifact.fitted_model_version
    assert body["active_model"] is not None
    assert body["active_model"]["artifact_id"] == artifact.artifact_id
    assert body["active_model"]["model_family"] == "poisson-regression"
    assert body["active_model"]["fitted_model_version"] == artifact.fitted_model_version
    assert body["active_model"]["training_dataset_id"] == "ds_admin_test"
    assert body["active_model"]["training_metrics"] == {
        "mae": 1.5,
        "rmse": 1.9,
        "walk_forward_aggregate_baseline_mae": 2.1,
        "walk_forward_aggregate_challenger_mae": 1.7,
    }
    assert body["active_model"]["activated_by"] == "tester"
    # An ACTIVE artifact is not "pending review" -- it's already live. Checked
    # by membership, not list equality: tests/integration/test_train_final_model.py
    # documents that model artifacts are append-only and some of its tests
    # deliberately leave permanent CANDIDATE rows in whatever database the
    # suite runs against, so a shared/reused dev database can carry pending
    # candidates left behind by earlier, unrelated test runs.
    pending_ids = [c["artifact_id"] for c in body["pending_model_candidates"]]
    assert artifact.artifact_id not in pending_ids


def test_admin_status_is_empty_pending_candidates_by_default(client):
    response = client.get("/api/admin/status", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    # Cannot assert the list is literally empty -- see the membership-based
    # assertion above for why a shared database may already carry candidates
    # left behind by other, legitimately permanent-commit tests. What must
    # always hold regardless of history: the field is wired up and every
    # entry it does contain is genuinely a pending candidate, never an
    # active/rejected artifact leaking into this list.
    assert isinstance(body["pending_model_candidates"], list)
    assert all(c["status"] == "CANDIDATE" for c in body["pending_model_candidates"])


def test_admin_status_surfaces_a_registered_but_unpromoted_candidate(client, db_session, monkeypatch):
    monkeypatch.setattr(admin_router, "get_git_commit_sha", lambda: "deadbeef1234")
    artifact = create_model_artifact(
        db_session,
        model_family="poisson-regression",
        model_code_version="poisson-regression-challenger-0.1.0",
        coefficients=[0.5, 0.1, 2.0, -0.02, 0.0],
        coefficient_order=[
            "intercept",
            "log1p_expected_bf",
            "recent_k_rate",
            "rest_days",
            "rest_days_missing",
        ],
        preprocessing_rules={},
        training_dataset_id="ds_pending_test",
        dataset_builder_version="v1",
        availability_policy_version="v1",
        feature_set_version="v1",
        training_seasons=[2023],
        training_game_types=["R"],
        training_row_count=400,
        trained_at=datetime(2026, 8, 6, tzinfo=UTC),
        dependency_versions={},
        training_metrics={
            "mae": 1.4,
            "walk_forward_aggregate_baseline_mae": 1.8,
            "walk_forward_aggregate_challenger_mae": 1.3,
        },
        evaluation_report_ids=[],
        created_by="auto-retrain-scheduler",
        notes="registered automatically",
    )
    register_as_candidate(db_session, artifact_id=artifact.artifact_id, operator="auto-retrain-scheduler")
    db_session.flush()

    response = client.get("/api/admin/status", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    # Not promoted -- still the permanent baseline actually serving.
    assert body["active_model"] is None
    # Found by artifact_id, not list length -- see the sibling tests above
    # for why a shared database may carry other permanently-committed
    # candidates left behind by unrelated test runs.
    candidates_by_id = {c["artifact_id"]: c for c in body["pending_model_candidates"]}
    assert artifact.artifact_id in candidates_by_id
    candidate = candidates_by_id[artifact.artifact_id]
    assert candidate["status"] == "CANDIDATE"
    assert candidate["created_by"] == "auto-retrain-scheduler"
    assert candidate["training_dataset_id"] == "ds_pending_test"

    assert candidate["notes"] == "registered automatically"


def test_admin_status_includes_a_zeroed_tracker_by_default(client):
    response = client.get("/api/admin/status", headers=AUTH)
    assert response.status_code == 200
    tracker = response.json()["tracker"]
    assert tracker["wins"] == 0
    assert tracker["losses"] == 0
    assert tracker["win_rate"] is None
    assert tracker["last_reset_by"] is None


def test_admin_status_tracker_reflects_real_grades(client, db_session):
    row = publish(
        db_session, game_id="api-admin-tracker-1", player_id="api-admin-tracker-player-1", line=3.5, mean=9.0
    )
    grade = Grade(
        grade_id=uuid4(), projection_id=row.projection_id, graded_at=datetime.now(UTC), result="WIN"
    )
    db_session.add(grade)
    db_session.flush()

    response = client.get("/api/admin/status", headers=AUTH)

    assert response.status_code == 200
    tracker = response.json()["tracker"]
    assert tracker["wins"] == 1
    assert tracker["win_rate"] == 1.0


def test_reset_tracker_endpoint_requires_auth(client):
    response = client.post("/api/admin/tracker/reset")
    assert response.status_code == 401


def test_reset_tracker_endpoint_zeroes_the_count_and_records_who(client, db_session):
    # graded_at is deliberately a fixed past date, not datetime.now(UTC):
    # this whole test runs inside one shared transaction (db_session/
    # client fixtures), and Postgres's now() -- what reset_tracker()'s
    # created_at server_default actually evaluates to -- is frozen at
    # that transaction's start, which is BEFORE any Python-side
    # datetime.now(UTC) call made later in the test body. A wall-clock
    # "before" timestamp would therefore already read as after the
    # reset's server-side timestamp, which only happens under this
    # single-shared-transaction test harness -- a real admin request is
    # its own separate transaction, so this ordering is never actually
    # ambiguous in production.
    row = publish(
        db_session, game_id="api-admin-tracker-2", player_id="api-admin-tracker-player-2", line=3.5, mean=9.0
    )
    grade = Grade(
        grade_id=uuid4(),
        projection_id=row.projection_id,
        graded_at=datetime(2020, 1, 1, tzinfo=UTC),
        result="LOSS",
    )
    db_session.add(grade)
    db_session.flush()

    before = client.get("/api/admin/status", headers=AUTH).json()["tracker"]
    assert before["losses"] == 1

    reset_response = client.post("/api/admin/tracker/reset", headers=AUTH, json={"operator": "tyler"})
    assert reset_response.status_code == 200
    reset_body = reset_response.json()
    assert reset_body["losses"] == 0
    assert reset_body["last_reset_by"] == "tyler"

    after = client.get("/api/admin/status", headers=AUTH).json()["tracker"]
    assert after["losses"] == 0
    assert after["last_reset_by"] == "tyler"

    # The underlying grade row itself is untouched -- only what the
    # tracker counts changed, never the permanent record.
    reloaded = db_session.get(Grade, grade.grade_id)
    assert reloaded is not None
    assert reloaded.result == "LOSS"
