"""Ingestion service integration tests -- real Postgres, real adapters,
verifying the raw row, source registry, source_health, and audit_event
all land correctly for both a success and a failure case."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select

from cassandra.adapters.park_factors_static import ParkFactorsStaticAdapter
from cassandra.adapters.umpire_stub import UmpireStubAdapter
from cassandra.db.models.audit import AuditEvent
from cassandra.db.models.raw import RawParkFactor
from cassandra.db.models.sources import Source, SourceHealth
from cassandra.identity_ids import mlb_venue_id
from cassandra.ingestion.ingest_service import _update_source_health, ingest

SLATE_DATE = date(2023, 6, 15)
NOW = datetime(2023, 6, 15, 12, 0, tzinfo=UTC)


def test_ingest_park_factors_end_to_end(db_session):
    adapter = ParkFactorsStaticAdapter()
    result = ingest(db_session, adapter, slate_date=SLATE_DATE, venue_ids=[2], run_id="test-run")
    db_session.flush()

    assert result.is_available
    assert result.records_written == 1

    source = db_session.get(Source, adapter.source_name)
    assert source is not None
    assert source.kind == "park"

    row = db_session.execute(
        select(RawParkFactor).where(RawParkFactor.venue_id == mlb_venue_id(2))
    ).scalar_one()
    assert row.k_factor == 1.00
    assert row.source_id == adapter.source_name
    assert row.ingested_at is not None
    assert row.observed_at is not None

    health = db_session.get(SourceHealth, adapter.source_name)
    assert health is not None
    assert health.last_status == "HEALTHY"
    assert health.consecutive_failures == 0

    events = (
        db_session.execute(
            select(AuditEvent).where(
                AuditEvent.event_type == "INGEST", AuditEvent.entity_id == adapter.source_name
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].payload["records_written"] == 1
    assert events[0].run_id == "test-run"


def test_ingest_unavailable_source_still_writes_audit_and_health(db_session):
    adapter = UmpireStubAdapter()
    result = ingest(db_session, adapter, slate_date=SLATE_DATE)
    db_session.flush()

    assert result.is_available is False
    assert result.records_written == 0
    assert result.warnings

    health = db_session.get(SourceHealth, adapter.source_name)
    assert health is not None
    # UmpireStubAdapter sets unavailable_reason="disabled" -- a permanent,
    # by-design stub, distinct from a real fetch failure (see
    # db/models/sources.py's SOURCE_HEALTH_STATES). consecutive_failures
    # counts real error streaks only -- an expected-unavailable state must
    # never increment it (Phase 1E fix), or a subsequent genuine error
    # would jump straight to FAILED instead of starting a fresh streak.
    assert health.last_status == "DISABLED"
    assert health.consecutive_failures == 0

    events = (
        db_session.execute(
            select(AuditEvent).where(
                AuditEvent.event_type == "INGEST", AuditEvent.entity_id == adapter.source_name
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].payload["is_available"] is False


def test_ingest_is_repeatable_and_append_only(db_session):
    """Running ingest twice must not mutate/replace the first row -- it
    appends a second raw row with a later ingested_at (ADR 0001)."""
    adapter = ParkFactorsStaticAdapter()
    ingest(db_session, adapter, slate_date=SLATE_DATE, venue_ids=[2])
    ingest(db_session, adapter, slate_date=SLATE_DATE, venue_ids=[2])
    db_session.flush()

    rows = (
        db_session.execute(select(RawParkFactor).where(RawParkFactor.venue_id == mlb_venue_id(2)))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert rows[0].raw_id != rows[1].raw_id


def test_pending_ticks_never_accumulate_consecutive_failures(db_session):
    # Regression for Phase 1E: a source that's legitimately PENDING for
    # many ticks in a row (e.g. a line that hasn't posted yet) must not
    # accumulate a large consecutive_failures count -- that counter exists
    # to track a streak of REAL errors, not expected/by-design absence.
    for _ in range(5):
        _update_source_health(db_session, "src-pending", NOW, success=False, unavailable_reason="pending")
    db_session.flush()

    health = db_session.get(SourceHealth, "src-pending")
    assert health is not None
    assert health.last_status == "PENDING"
    assert health.consecutive_failures == 0


def test_quota_limited_ticks_never_accumulate_consecutive_failures(db_session):
    for _ in range(5):
        _update_source_health(db_session, "src-quota", NOW, success=False, unavailable_reason="quota_limited")
    db_session.flush()

    health = db_session.get(SourceHealth, "src-quota")
    assert health is not None
    assert health.last_status == "QUOTA_LIMITED"
    assert health.consecutive_failures == 0


def test_real_errors_still_accumulate_consecutive_failures(db_session):
    # A genuine fetch error (unspecified/"error" reason) must still count
    # normally -- this fix narrows what counts as a failure, it doesn't
    # stop counting real ones.
    for _ in range(2):
        _update_source_health(db_session, "src-real-error", NOW, success=False, unavailable_reason=None)
    db_session.flush()

    health = db_session.get(SourceHealth, "src-real-error")
    assert health is not None
    assert health.consecutive_failures == 2
    assert health.last_status == "DEGRADED"  # below the FAILED threshold of 3


def test_a_real_error_after_a_long_pending_streak_starts_a_fresh_streak_not_failed(db_session):
    # The actual bug this fix closes: before 1E, a long PENDING streak
    # inflated consecutive_failures, so the very first REAL error after
    # it would immediately read as FAILED (three-in-a-row) instead of the
    # first error of a brand new streak (DEGRADED).
    for _ in range(10):
        _update_source_health(db_session, "src-mixed", NOW, success=False, unavailable_reason="pending")
    _update_source_health(db_session, "src-mixed", NOW, success=False, unavailable_reason=None)
    db_session.flush()

    health = db_session.get(SourceHealth, "src-mixed")
    assert health is not None
    assert health.consecutive_failures == 1
    assert health.last_status == "DEGRADED"


def test_success_still_resets_consecutive_failures_to_zero(db_session):
    _update_source_health(db_session, "src-recovers", NOW, success=False, unavailable_reason=None)
    _update_source_health(db_session, "src-recovers", NOW, success=False, unavailable_reason=None)
    _update_source_health(db_session, "src-recovers", NOW, success=True, unavailable_reason=None)
    db_session.flush()

    health = db_session.get(SourceHealth, "src-recovers")
    assert health is not None
    assert health.consecutive_failures == 0
    assert health.last_status == "HEALTHY"
