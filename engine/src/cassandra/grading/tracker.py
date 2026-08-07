"""Resettable win/loss tracker for the Admin page -- a running count of
real graded outcomes (WIN/LOSS/PUSH/VOID/NO_PLAY on LIVE-labeled
projections) since the last reset, so an operator can watch how the
platform is actually performing and restart the count at a clean 0-0
whenever they want (e.g. right after promoting a new challenger).

CLAUDE.md non-negotiable #6: "Losses are never deleted." A reset can
never mean touching a grades row -- it only ever records a new
"tracker_reset" audit_events row (append-only, same pattern as
orchestration/retraining_scheduler.py's "retrain_attempted" events). The
tracker's counts are always computed live from the real grades table,
filtered to graded_at >= the latest reset's timestamp (or the epoch if
never reset) -- so "resetting" changes what's counted, never what
happened. The permanent, un-resettable full history is still exactly
what the Ledger page already shows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cassandra.db.models.audit import AuditEvent
from cassandra.db.models.grading import Grade
from cassandra.db.models.projection import Projection

TRACKER_MODULE_VERSION = "grading-tracker-0.1.0"

TRACKER_RESET_EVENT_TYPE = "tracker_reset"

# The tracker's implicit start when it has never been reset -- no real
# grade can predate this, so this sentinel avoids a nullable "no filter"
# branch in the summary query below.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class TrackerSummary:
    wins: int
    losses: int
    pushes: int
    voids: int
    no_plays: int
    win_rate: float | None  # wins / (wins + losses); None when that's 0/0
    tracker_started_at: datetime
    last_reset_by: str | None


def latest_tracker_reset(session: Session) -> AuditEvent | None:
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.event_type == TRACKER_RESET_EVENT_TYPE)
        .order_by(AuditEvent.created_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalars().first()


def reset_tracker(session: Session, *, operator: str) -> AuditEvent:
    """Records a new tracker_reset event -- never touches any grades row.
    The tracker's "counting since" timestamp becomes this event's
    created_at once committed."""
    event = AuditEvent(
        event_type=TRACKER_RESET_EVENT_TYPE,
        entity_type="tracker",
        actor=operator,
        payload={"reset_by": operator},
    )
    session.add(event)
    session.flush()
    return event


def tracker_summary(session: Session) -> TrackerSummary:
    """Counts CURRENT grades (latest graded_at per projection_id, the
    same derived-by-query "current" pattern as
    current_grades_for_projections) for LIVE-labeled projections graded
    since the latest reset. Read-only -- never writes anything."""
    last_reset = latest_tracker_reset(session)
    since = last_reset.created_at if last_reset is not None else _EPOCH

    current_grade_ids = (
        select(Grade.grade_id)
        .order_by(Grade.projection_id, Grade.graded_at.desc())
        .distinct(Grade.projection_id)
        .subquery()
    )
    stmt = (
        select(Grade.result, func.count())
        .join(current_grade_ids, Grade.grade_id == current_grade_ids.c.grade_id)
        .join(Projection, Projection.projection_id == Grade.projection_id)
        .where(Projection.record_label == "LIVE", Grade.graded_at >= since)
        .group_by(Grade.result)
    )
    counts: dict[str, int] = {}
    for result, count in session.execute(stmt):
        counts[result] = count

    wins = counts.get("WIN", 0)
    losses = counts.get("LOSS", 0)
    pushes = counts.get("PUSH", 0)
    voids = counts.get("VOID", 0)
    no_plays = counts.get("NO_PLAY", 0)
    decided = wins + losses
    win_rate = wins / decided if decided > 0 else None

    return TrackerSummary(
        wins=wins,
        losses=losses,
        pushes=pushes,
        voids=voids,
        no_plays=no_plays,
        win_rate=win_rate,
        tracker_started_at=since,
        last_reset_by=last_reset.actor if last_reset is not None else None,
    )


__all__ = [
    "TRACKER_MODULE_VERSION",
    "TRACKER_RESET_EVENT_TYPE",
    "TrackerSummary",
    "latest_tracker_reset",
    "reset_tracker",
    "tracker_summary",
]
