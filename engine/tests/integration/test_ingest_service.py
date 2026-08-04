"""Ingestion service integration tests -- real Postgres, real adapters,
verifying the raw row, source registry, source_health, and audit_event
all land correctly for both a success and a failure case."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from cassandra.adapters.park_factors_static import ParkFactorsStaticAdapter
from cassandra.adapters.umpire_stub import UmpireStubAdapter
from cassandra.db.models.audit import AuditEvent
from cassandra.db.models.raw import RawParkFactor
from cassandra.db.models.sources import Source, SourceHealth
from cassandra.identity_ids import mlb_venue_id
from cassandra.ingestion.ingest_service import ingest

SLATE_DATE = date(2023, 6, 15)


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
    assert health.last_status == "ok"
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
    assert health.last_status == "unavailable"
    assert health.consecutive_failures == 1

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
