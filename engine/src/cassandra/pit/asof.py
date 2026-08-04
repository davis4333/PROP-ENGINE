"""The point-in-time / as-of query gate (ADR 0001). Every historical
feature/snapshot read of a raw_* table must go through this module,
never a direct query -- see docs/adr/0001, CLAUDE.md's do-not-do list,
and the cassandra-pit-audit skill.

`raw_final_box_scores` is never read here -- grading/ is the only module
allowed to query it, and only for `game_status='Final'` rows. That
structural exclusion (this module simply has no function for it) is a
second, independent safeguard beyond the timestamp filter.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from cassandra.db.base import Base


def latest_as_of[ModelT: Base](
    session: Session,
    model: type[ModelT],
    natural_key: dict[str, object],
    cutoff: datetime,
) -> ModelT | None:
    """The single as-of primitive: among rows matching `natural_key` where
    BOTH `ingested_at <= cutoff` AND `observed_at <= cutoff` hold, return
    the one with the latest `(observed_at, ingested_at)` -- or None if no
    row qualifies (a legitimate, expected outcome the caller must handle
    visibly, e.g. via DATA_MISSING, never by silently proceeding).

    `ingested_at` is the true leakage gate (when this system could
    actually have known the fact); `observed_at` is an independent second
    filter against a source backdating its claimed effective time. Both
    must hold -- see ADR 0001.
    """
    if cutoff.tzinfo is None:
        raise ValueError("cutoff must be timezone-aware (UTC)")

    conditions = [getattr(model, key) == value for key, value in natural_key.items()]
    stmt = (
        select(model)
        .where(*conditions)
        .where(model.ingested_at <= cutoff, model.observed_at <= cutoff)  # type: ignore[attr-defined]
        .order_by(model.observed_at.desc(), model.ingested_at.desc())  # type: ignore[attr-defined]
        .limit(1)
    )
    return session.execute(stmt).scalars().first()


def all_as_of[ModelT: Base](
    session: Session,
    model: type[ModelT],
    natural_key: dict[str, object],
    cutoff: datetime,
) -> list[ModelT]:
    """All rows matching `natural_key` visible as-of `cutoff`, latest
    first. Used where a feature needs the recent *history* (e.g. a
    pitcher's last N starts), not just the single latest fact."""
    if cutoff.tzinfo is None:
        raise ValueError("cutoff must be timezone-aware (UTC)")

    conditions = [getattr(model, key) == value for key, value in natural_key.items()]
    stmt = (
        select(model)
        .where(*conditions)
        .where(model.ingested_at <= cutoff, model.observed_at <= cutoff)  # type: ignore[attr-defined]
        .order_by(model.observed_at.desc(), model.ingested_at.desc())  # type: ignore[attr-defined]
    )
    return list(session.execute(stmt).scalars().all())


def latest_grouped_as_of[ModelT: Base](
    session: Session,
    model: type[ModelT],
    natural_key: dict[str, object],
    cutoff: datetime,
    group_by: str,
) -> list[ModelT]:
    """Like `all_as_of`, collapsed to the single latest row per distinct
    value of `group_by` -- e.g. a game's home *and* away probable pitcher
    both match `{"mlb_game_pk": ...}`, but each team needs its own latest
    row, not the single overall latest."""
    rows = all_as_of(session, model, natural_key, cutoff)  # already latest-first
    seen: dict[object, ModelT] = {}
    for row in rows:
        key = getattr(row, group_by)
        if key not in seen:
            seen[key] = row
    return list(seen.values())
