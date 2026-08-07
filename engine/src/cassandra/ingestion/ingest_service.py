"""Generic ingestion: adapter -> raw table, with source registry/health
and audit-event bookkeeping. See the cassandra-data-adapter skill.

`ingest()` is deliberately adapter-agnostic (it only relies on the
`SourceAdapter` contract), except for two narrow, explicitly-named side
effects: after ingesting a schedule or probable-pitcher adapter's
records, it also upserts the resulting identity rows (venues/teams/games/
players) via identity_resolver.py, since those raw payloads are the only
place that identity data comes from. Every other adapter's ingestion is
fully generic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from cassandra.adapters.base import SourceAdapter
from cassandra.adapters.probable_pitchers_mlb import ProbablePitchersMLBAdapter
from cassandra.adapters.schedule_mlb import ScheduleMLBAdapter
from cassandra.db.models.audit import AuditEvent
from cassandra.db.models.sources import Source, SourceHealth
from cassandra.ingestion.identity_resolver import (
    resolve_identity_from_probable_pitcher_payload,
    resolve_identity_from_schedule_payload,
)


@dataclass
class IngestResult:
    source_name: str
    records_written: int
    is_available: bool
    warnings: list[str]


def ensure_source(session: Session, adapter: SourceAdapter, base_url: str | None = None) -> str:
    """Idempotently register this adapter in the source registry. Returns
    the source_id."""
    source_id = adapter.source_name
    stmt = pg_insert(Source).values(
        source_id=source_id,
        name=adapter.source_name,
        kind=adapter.kind,
        adapter_version=adapter.adapter_version,
        base_url=base_url,
        is_active=True,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Source.source_id],
        set_={"adapter_version": adapter.adapter_version, "is_active": True},
    )
    session.execute(stmt)
    return source_id


def ingest(
    session: Session,
    adapter: SourceAdapter,
    *,
    slate_date: date,
    as_of: datetime | None = None,
    run_id: str | None = None,
    **fetch_kwargs: object,
) -> IngestResult:
    """Fetch this adapter's records for the slate and write them to its
    raw table, updating source_health and writing an audit_event either
    way (success or failure -- failure is a visible, auditable outcome,
    never a silent gap)."""
    source_id = ensure_source(session, adapter)
    now = datetime.now(UTC)

    result = adapter.fetch(slate_date=slate_date, as_of=as_of, **fetch_kwargs)

    written = 0
    if result.is_available:
        model_columns = {c.key for c in adapter.raw_model.__table__.columns}
        for record in result.records:
            kwargs: dict[str, object] = dict(record.fields)
            kwargs["source_id"] = source_id
            kwargs["ingested_at"] = now
            kwargs["observed_at"] = record.observed_at
            kwargs["payload"] = record.payload
            if "record_hash" in model_columns and record.record_hash is not None:
                kwargs["record_hash"] = record.record_hash
            session.add(adapter.raw_model(**kwargs))
            written += 1

        if isinstance(adapter, ScheduleMLBAdapter):
            for record in result.records:
                resolve_identity_from_schedule_payload(session, record.payload)
        elif isinstance(adapter, ProbablePitchersMLBAdapter):
            for record in result.records:
                resolve_identity_from_probable_pitcher_payload(session, record.payload)

    _update_source_health(
        session, source_id, now, success=result.is_available, unavailable_reason=result.unavailable_reason
    )
    session.add(
        AuditEvent(
            event_type="INGEST",
            entity_type="source",
            entity_id=source_id,
            run_id=run_id,
            payload={
                "slate_date": slate_date.isoformat(),
                "records_written": written,
                "is_available": result.is_available,
                "warnings": result.warnings,
            },
        )
    )

    return IngestResult(
        source_name=adapter.source_name,
        records_written=written,
        is_available=result.is_available,
        warnings=result.warnings,
    )


# Mirrors api/routers/admin.py's CONSECUTIVE_FAILURE_ALERT_THRESHOLD --
# a real ("error"-reason or unspecified) failure only escalates from
# DEGRADED to FAILED once it's failed this many times in a row, matching
# the same threshold the blocking-issues check uses. Duplicated as a
# literal rather than imported to avoid ingestion/ importing api/ (the
# dependency should run the other way -- admin reads ingestion's output).
_DEGRADED_TO_FAILED_THRESHOLD = 3


def _source_health_status(*, success: bool, unavailable_reason: str | None, consecutive_failures: int) -> str:
    if success:
        return "HEALTHY"
    if unavailable_reason == "disabled":
        return "DISABLED"
    if unavailable_reason == "pending":
        return "PENDING"
    if unavailable_reason == "quota_limited":
        return "QUOTA_LIMITED"
    # "error" or unspecified -- a real failure, escalating from DEGRADED
    # (transient, still worth a closer look before alarming) to FAILED
    # once it's persisted.
    return "FAILED" if consecutive_failures >= _DEGRADED_TO_FAILED_THRESHOLD else "DEGRADED"


# Reasons an "unavailable" tick is expected/by-design, not a real fetch
# error -- see db/models/sources.py's SOURCE_HEALTH_STATES. These must
# never feed consecutive_failures, which exists specifically to count a
# streak of REAL errors (the DEGRADED->FAILED escalation). A source that's
# legitimately PENDING for hours (e.g. a line that hasn't posted yet)
# must not silently arrive at FAILED the instant a genuine error occurs,
# just because the counter was never actually counting failures.
_EXPECTED_UNAVAILABLE_REASONS = frozenset({"pending", "disabled", "quota_limited"})


def _update_source_health(
    session: Session,
    source_id: str,
    now: datetime,
    *,
    success: bool,
    unavailable_reason: str | None = None,
) -> None:
    is_real_failure = not success and unavailable_reason not in _EXPECTED_UNAVAILABLE_REASONS
    existing = session.get(SourceHealth, source_id)
    if existing is None:
        consecutive_failures = 1 if is_real_failure else 0
        session.add(
            SourceHealth(
                source_id=source_id,
                last_success_at=now if success else None,
                last_failure_at=None if success else now,
                last_status=_source_health_status(
                    success=success,
                    unavailable_reason=unavailable_reason,
                    consecutive_failures=consecutive_failures,
                ),
                consecutive_failures=consecutive_failures,
            )
        )
        return
    existing.updated_at = now
    if success:
        existing.last_success_at = now
        existing.consecutive_failures = 0
    else:
        existing.last_failure_at = now
        if is_real_failure:
            existing.consecutive_failures = existing.consecutive_failures + 1
    existing.last_status = _source_health_status(
        success=success,
        unavailable_reason=unavailable_reason,
        consecutive_failures=existing.consecutive_failures,
    )
