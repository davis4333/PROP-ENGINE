"""Regression tests for a real bug found by an independent audit:
run_slate()/grade_slate_run() used to mark a run "failed" and add a
RUN_FAILED audit event on the SAME session the caller's db/session.py
session_scope() rolls back on any exception -- so a failed pipeline run
left literally zero trace in the database (no PipelineRun row, no
PipelineRunStage rows, no audit event at all), even though the run
genuinely happened and genuinely failed.

These tests inject a real failure at each of the four stages that do
real work (INGEST/FREEZE/PROJECT/PUBLISH -- VALIDATE has no separate code
path, REVIEW is pure in-memory computation with nothing to fail against a
real backend) and confirm a durable PipelineRun(status="failed") +
RUN_FAILED AuditEvent survive even though the caller's own session (here,
the shared rollback-based `db_session` fixture) is never committed.

That admin/status endpoints correctly SURFACE an existing failed-run row
is already covered by tests/api/test_admin_router.py's
test_admin_status_surfaces_source_health_and_failed_run_as_blocking
(which seeds one directly) -- these tests exist to prove the row gets
written in the first place, not to re-prove how it's displayed.

Uses the exact same real fixture data (2023-06-15 Blue Jays @ Orioles
slate) as test_run_slate.py's successful end-to-end test, imported
directly rather than duplicated.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import delete, select
from tests.integration.test_run_slate import (
    SLATE_DATE,
    _feed_side_effect,
    _gamelog_side_effect,
    _lines_drop_dir,
    _load,
)

import cassandra.orchestration.run_slate as run_slate_module
from cassandra.adapters.final_box_scores_mlb import LIVE_FEED_BASE
from cassandra.adapters.schedule_mlb import MLB_STATS_API_BASE
from cassandra.adapters.weather_openmeteo import ARCHIVE_URL
from cassandra.db.models.audit import AuditEvent
from cassandra.db.models.pipeline import PipelineRun, PipelineRunStage
from cassandra.db.models.projection import Projection
from cassandra.orchestration.run_slate import run_slate


def _mock_ingest_sources() -> None:
    """The same respx mocks test_run_slate.py's successful end-to-end
    test uses -- everything INGEST needs to actually succeed for real, so
    a test injecting a failure downstream of INGEST exercises real
    upstream data, not a shortcut."""
    respx.get(f"{MLB_STATS_API_BASE}/schedule").mock(
        return_value=httpx.Response(200, json=_load("schedule_2023-06-15.json"))
    )
    respx.route(url__regex=rf"{re.escape(MLB_STATS_API_BASE)}/people/\d+/stats").mock(
        side_effect=_gamelog_side_effect
    )
    respx.get(ARCHIVE_URL).mock(return_value=httpx.Response(200, json=_load("weather_archive_camden.json")))
    respx.route(url__regex=rf"{re.escape(LIVE_FEED_BASE)}/game/\d+/feed/live").mock(
        side_effect=_feed_side_effect
    )


def _cleanup_run(run_id: str) -> None:
    """_record_failed_run commits via its OWN independent session
    (db/session.py's session_scope(), a different connection than the
    test's db_session fixture) -- deliberately, so the failure record
    survives db_session's own rollback-based teardown. That also means
    db_session's rollback can never clean these rows back up, so this
    explicit cleanup (its own real commit) is required, matching the same
    pattern test_historical_backfill.py/test_dataset_builder.py already
    use for the same underlying reason (code under test that commits for
    itself).

    Deliberately does NOT delete AuditEvent or Projection rows -- found
    while writing this cleanup: both tables have DELETE revoked at the
    database grant level (CLAUDE.md non-negotiable #3, db/migrations/
    versions/f4b13ecb5ad7's IMMUTABLE_TABLES), so attempting to would
    raise a real permission error, not silently no-op. This is correct,
    not a workaround: a real failed run's audit trail is exactly as
    permanent as a real successful run's, by the same design. Only
    pipeline_runs/pipeline_run_stages are genuinely mutable operational
    tracking (see db/models/pipeline.py's own docstrings) and safe to
    clean up here."""
    from cassandra.db.session import session_scope

    with session_scope() as session:
        session.execute(delete(PipelineRunStage).where(PipelineRunStage.run_id == run_id))
        session.execute(delete(PipelineRun).where(PipelineRun.run_id == run_id))


@respx.mock
def test_ingest_failure_leaves_a_durable_failed_run(db_session, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("synthetic INGEST failure")

    monkeypatch.setattr(run_slate_module, "ingest_slate", _boom)

    cutoff_at = datetime.now(UTC) + timedelta(minutes=2)
    run_id = None
    try:
        run_slate(db_session, SLATE_DATE, cutoff_at)
    except RuntimeError:
        pass
    else:
        pytest.fail("expected RuntimeError to propagate")

    # The failure record must be visible even though db_session's own
    # transaction (everything run_slate() itself wrote) was just rolled
    # back -- it was written durably via a completely separate session.
    from cassandra.db.session import session_scope

    with session_scope() as verify_session:
        run = verify_session.execute(
            select(PipelineRun).where(PipelineRun.slate_date == SLATE_DATE, PipelineRun.status == "failed")
        ).scalar_one()
        run_id = run.run_id
        assert run.current_stage == "INGEST"

        stage = verify_session.execute(
            select(PipelineRunStage).where(
                PipelineRunStage.run_id == run_id, PipelineRunStage.stage == "INGEST"
            )
        ).scalar_one()
        assert stage.status == "failed"
        assert "synthetic INGEST failure" in (stage.detail or "")

        event = verify_session.execute(
            select(AuditEvent).where(AuditEvent.run_id == run_id, AuditEvent.event_type == "RUN_FAILED")
        ).scalar_one()
        assert event.payload["failed_stage"] == "INGEST"
        assert event.payload["error_class"] == "RuntimeError"

    _cleanup_run(run_id)


@respx.mock
def test_freeze_failure_leaves_a_durable_failed_run_with_ingest_recorded_as_succeeded(
    db_session, monkeypatch, tmp_path
):
    _mock_ingest_sources()

    def _boom(*args, **kwargs):
        raise RuntimeError("synthetic FREEZE failure")

    monkeypatch.setattr(run_slate_module, "build_snapshot", _boom)

    cutoff_at = datetime.now(UTC) + timedelta(minutes=2)
    lines_drop_dir = _lines_drop_dir(tmp_path)
    run_id = None
    try:
        run_slate(db_session, SLATE_DATE, cutoff_at, lines_drop_dir=lines_drop_dir)
    except RuntimeError:
        pass
    else:
        pytest.fail("expected RuntimeError to propagate")

    from cassandra.db.session import session_scope

    with session_scope() as verify_session:
        run = verify_session.execute(
            select(PipelineRun).where(PipelineRun.slate_date == SLATE_DATE, PipelineRun.status == "failed")
        ).scalar_one()
        run_id = run.run_id
        assert run.current_stage == "FREEZE"

        stages = {
            s.stage: s.status
            for s in verify_session.execute(
                select(PipelineRunStage).where(PipelineRunStage.run_id == run_id)
            ).scalars()
        }
        # INGEST genuinely completed before FREEZE failed -- that must be
        # durably recorded too, not just "something failed somewhere."
        assert stages["INGEST"] == "succeeded"
        assert stages["VALIDATE"] == "succeeded"
        assert stages["FREEZE"] == "failed"

    _cleanup_run(run_id)


@respx.mock
def test_project_failure_leaves_a_durable_failed_run(db_session, monkeypatch, tmp_path):
    _mock_ingest_sources()

    def _boom(*args, **kwargs):
        raise RuntimeError("synthetic PROJECT failure")

    monkeypatch.setattr(run_slate_module, "build_features", _boom)

    cutoff_at = datetime.now(UTC) + timedelta(minutes=2)
    lines_drop_dir = _lines_drop_dir(tmp_path)
    run_id = None
    try:
        run_slate(db_session, SLATE_DATE, cutoff_at, lines_drop_dir=lines_drop_dir)
    except RuntimeError:
        pass
    else:
        pytest.fail("expected RuntimeError to propagate")

    from cassandra.db.session import session_scope

    with session_scope() as verify_session:
        run = verify_session.execute(
            select(PipelineRun).where(PipelineRun.slate_date == SLATE_DATE, PipelineRun.status == "failed")
        ).scalar_one()
        run_id = run.run_id
        assert run.current_stage == "PROJECT"

        stages = {
            s.stage: s.status
            for s in verify_session.execute(
                select(PipelineRunStage).where(PipelineRunStage.run_id == run_id)
            ).scalars()
        }
        assert stages["INGEST"] == "succeeded"
        assert stages["FREEZE"] == "succeeded"
        assert stages["PROJECT"] == "failed"

    _cleanup_run(run_id)


@respx.mock
def test_publish_failure_leaves_a_durable_failed_run_and_no_partial_projections_survive(
    db_session, monkeypatch, tmp_path
):
    _mock_ingest_sources()

    call_count = {"n": 0}
    real_publish_projection = run_slate_module.publish_projection

    def _fail_on_second_call(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("synthetic PUBLISH failure")
        return real_publish_projection(*args, **kwargs)

    monkeypatch.setattr(run_slate_module, "publish_projection", _fail_on_second_call)

    cutoff_at = datetime.now(UTC) + timedelta(minutes=2)
    lines_drop_dir = _lines_drop_dir(tmp_path)
    run_id = None
    try:
        run_slate(db_session, SLATE_DATE, cutoff_at, lines_drop_dir=lines_drop_dir)
    except RuntimeError:
        pass
    else:
        pytest.fail("expected RuntimeError to propagate")

    # confirms the injected failure actually fired mid-PUBLISH, after one
    # real projection had already been written to (the now-rolled-back)
    # db_session -- the real point of this test is the run_id-scoped
    # check below: that partial business data must NOT survive as part
    # of a failed run (append-only ledger integrity -- a projection
    # either fully belongs to a real published run or doesn't exist at
    # all, never a half-written one).
    assert call_count["n"] == 2

    from cassandra.db.session import session_scope

    with session_scope() as verify_session:
        run = verify_session.execute(
            select(PipelineRun).where(PipelineRun.slate_date == SLATE_DATE, PipelineRun.status == "failed")
        ).scalar_one()
        run_id = run.run_id
        assert run.current_stage == "PUBLISH"

        stages = {
            s.stage: s.status
            for s in verify_session.execute(
                select(PipelineRunStage).where(PipelineRunStage.run_id == run_id)
            ).scalars()
        }
        assert stages["INGEST"] == "succeeded"
        assert stages["FREEZE"] == "succeeded"
        assert stages["PROJECT"] == "succeeded"
        assert stages["REVIEW"] == "succeeded"
        assert stages["PUBLISH"] == "failed"
        # No durable projections table row exists for this failed run --
        # the failure record's existence never implies any business data
        # from that run actually landed.
        no_projections = verify_session.execute(select(Projection).where(Projection.run_id == run_id)).all()
        assert no_projections == []

    _cleanup_run(run_id)


@respx.mock
def test_failed_run_error_detail_never_leaks_a_url_embedded_secret(db_session, monkeypatch, tmp_path):
    """A real scenario this failure path must defend against: an
    httpx.HTTPStatusError (or any httpx.RequestError) bubbling up
    unhandled embeds the full request URL in its own __str__ --
    adapters/lines_odds_api.py's real vendor integration passes its API
    key as a query parameter, so a naive str(exc) anywhere in this path
    would leak a live credential into the permanent, undeletable
    audit_events table."""
    _mock_ingest_sources()

    fake_secret = "sk_live_totally_fake_secret_value_12345"
    request = httpx.Request("GET", f"https://example.com/odds?apiKey={fake_secret}")
    response = httpx.Response(401, request=request)

    def _boom(*args, **kwargs):
        raise httpx.HTTPStatusError("401 Unauthorized", request=request, response=response)

    monkeypatch.setattr(run_slate_module, "build_snapshot", _boom)

    cutoff_at = datetime.now(UTC) + timedelta(minutes=2)
    lines_drop_dir = _lines_drop_dir(tmp_path)
    run_id = None
    try:
        run_slate(db_session, SLATE_DATE, cutoff_at, lines_drop_dir=lines_drop_dir)
    except httpx.HTTPStatusError:
        pass
    else:
        pytest.fail("expected httpx.HTTPStatusError to propagate")

    from cassandra.db.session import session_scope

    with session_scope() as verify_session:
        run = verify_session.execute(
            select(PipelineRun).where(PipelineRun.slate_date == SLATE_DATE, PipelineRun.status == "failed")
        ).scalar_one()
        run_id = run.run_id

        stage = verify_session.execute(
            select(PipelineRunStage).where(
                PipelineRunStage.run_id == run_id, PipelineRunStage.stage == "FREEZE"
            )
        ).scalar_one()
        event = verify_session.execute(
            select(AuditEvent).where(AuditEvent.run_id == run_id, AuditEvent.event_type == "RUN_FAILED")
        ).scalar_one()

        assert fake_secret not in (stage.detail or "")
        assert fake_secret not in str(event.payload)
        # Still real, useful information -- just not the raw exception
        # string this specific exception type would otherwise embed.
        assert "401" in (stage.detail or "")

    _cleanup_run(run_id)
