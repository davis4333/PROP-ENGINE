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

from sqlalchemy.dialects.postgresql import insert as pg_insert

from cassandra.api import deps
from cassandra.config import settings
from cassandra.db.models.identity import Game, Player
from cassandra.db.models.pipeline import PipelineRun, PipelineRunStage
from cassandra.db.models.raw import RawProbablePitcher
from cassandra.db.models.sources import Source, SourceHealth

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
    stmt = pg_insert(Source).values(source_id="umpire_stub", name="umpire_stub", kind="umpire")
    db_session.execute(stmt)
    db_session.add(
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
