"""orchestration/retraining_scheduler.py's _last_retrain_attempt_at()
against a real Postgres session -- proves the actual SQL correctly finds
the latest "retrain_attempted" audit_events row (never an older one, and
never a differently-typed audit event), which should_trigger_retrain()'s
DB-derived restart-safety cadence depends on."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cassandra.db.models.audit import AuditEvent
from cassandra.orchestration.retraining_scheduler import _last_retrain_attempt_at


def _add_event(db_session, *, event_type: str, created_at: datetime) -> None:
    db_session.add(
        AuditEvent(
            event_type=event_type,
            entity_type="model_artifact",
            actor="test",
            created_at=created_at,
        )
    )
    db_session.flush()


def test_none_when_no_retrain_attempt_has_ever_happened(db_session):
    assert _last_retrain_attempt_at(db_session) is None


def test_ignores_other_event_types(db_session):
    _add_event(db_session, event_type="INGEST", created_at=datetime.now(UTC))
    assert _last_retrain_attempt_at(db_session) is None


def test_returns_the_single_attempt(db_session):
    when = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    _add_event(db_session, event_type="retrain_attempted", created_at=when)
    assert _last_retrain_attempt_at(db_session) == when


def test_returns_the_latest_of_several_attempts(db_session):
    earlier = datetime(2026, 7, 25, tzinfo=UTC)
    later = datetime(2026, 8, 1, tzinfo=UTC)
    _add_event(db_session, event_type="retrain_attempted", created_at=earlier)
    _add_event(db_session, event_type="retrain_attempted", created_at=later)
    assert _last_retrain_attempt_at(db_session) == later


def test_a_later_unrelated_event_does_not_shadow_the_real_attempt(db_session):
    attempt_at = datetime(2026, 8, 1, tzinfo=UTC)
    _add_event(db_session, event_type="retrain_attempted", created_at=attempt_at)
    _add_event(db_session, event_type="INGEST", created_at=attempt_at + timedelta(hours=1))
    assert _last_retrain_attempt_at(db_session) == attempt_at
