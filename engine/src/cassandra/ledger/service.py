"""The append-only projection ledger writer. Never UPDATEs a `projections`
row -- see CLAUDE.md's do-not-do list and ADR 0002. "Current" is always
derived by query (`current_projections_for_slate` /
`current_projection_versions`), never by a mutable flag.

Publication is a distinct concept from being evaluated or qualified
(ADR 0002): every call here writes a row (the full transparency record),
but only `publish=True` calls set `published_at`. A projection published
inside the official pregame freeze window --
`settings.publication_freeze_minutes_before_first_pitch` before the
game's scheduled start, a provisional/configurable default (ADR 0008) --
is labeled `is_late_publication=True` and must be excluded from official
public performance aggregates by readers, not by hiding the row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, select
from sqlalchemy.orm import Session

from cassandra.config import get_git_commit_sha, settings
from cassandra.db.models.audit import AuditEvent
from cassandra.db.models.identity import Game
from cassandra.db.models.projection import Projection
from cassandra.db.models.snapshot import Snapshot
from cassandra.decision.engine import Decision, reproducibility_hash

MARKET = "pitcher_strikeouts"


def logical_key_for(player_id: str, game_id: str, market: str = MARKET) -> str:
    return f"{player_id}|{game_id}|{market}"


def latest_version(session: Session, logical_key: str) -> Projection | None:
    stmt = (
        select(Projection)
        .where(Projection.logical_key == logical_key)
        .order_by(Projection.version.desc())
        .limit(1)
    )
    return session.execute(stmt).scalars().first()


def publish_projection(
    session: Session,
    *,
    run_id: str,
    snapshot: Snapshot,
    game: Game,
    player_id: str,
    line: float | None,
    feature_set_version: str,
    features: dict[str, object],
    model_version: str,
    decision: Decision,
    as_of: datetime,
    publish: bool = True,
) -> Projection:
    """Writes a new (or version-superseding) projections row. Always an
    INSERT -- rerunning a slate never mutates a prior row.

    `line=None` is legitimate: it means no market line was found for this
    player/game as of the freeze cutoff (MARKET_CONTEXT_INCOMPLETE, a fail
    finding decide() already turned into REJECTED/NO_PLAY) -- the
    projection is still logged for transparency, just with no line to
    grade against later."""
    logical_key = logical_key_for(player_id, game.game_id)
    existing = latest_version(session, logical_key)
    version = (existing.version + 1) if existing else 1

    git_sha = get_git_commit_sha()
    repro_hash = reproducibility_hash(
        source_snapshot_id=str(snapshot.snapshot_id),
        feature_set_version=feature_set_version,
        features=features,
        model_version=model_version,
        decision_policy_version=decision.decision_policy_version,
        edge_threshold=settings.decision_edge_threshold,
        git_commit_sha=git_sha,
    )

    published_at = datetime.now(UTC) if publish else None
    # ADR 0008's official publication cutoff: not the literal first-pitch
    # moment, but settings.publication_freeze_minutes_before_first_pitch
    # (a provisional, configurable default) before it -- a publication
    # landing inside that freeze window is still logged in full, just
    # never counted as the official pregame pick.
    official_cutoff = (
        game.scheduled_start_utc - timedelta(minutes=settings.publication_freeze_minutes_before_first_pitch)
        if game.scheduled_start_utc
        else None
    )
    is_late = bool(published_at and official_cutoff and published_at > official_cutoff)

    row = Projection(
        projection_id=f"proj_{uuid.uuid4().hex[:20]}",
        logical_key=logical_key,
        version=version,
        supersedes_projection_id=existing.projection_id if existing else None,
        run_id=run_id,
        as_of=as_of,
        sport="MLB",
        market=MARKET,
        player_id=player_id,
        game_id=game.game_id,
        line=line,
        projection_mean=decision.projection_mean,
        projection_sd=decision.projection_sd,
        probability_over=decision.probability_over,
        probability_under=decision.probability_under,
        decision=decision.decision,
        decision_status=decision.decision_status,
        reason_codes=decision.reason_codes,
        model_version=model_version,
        feature_set_version=feature_set_version,
        decision_policy_version=decision.decision_policy_version,
        source_snapshot_id=snapshot.snapshot_id,
        reproducibility_hash=repro_hash,
        git_commit_sha=git_sha,
        published_at=published_at,
        is_late_publication=is_late,
    )
    session.add(row)
    session.add(
        AuditEvent(
            event_type="PUBLISH" if publish else "EVALUATE",
            entity_type="projection",
            entity_id=row.projection_id,
            run_id=run_id,
            payload={
                "logical_key": logical_key,
                "version": version,
                "decision": decision.decision,
                "decision_status": decision.decision_status,
                "is_late_publication": is_late,
            },
        )
    )
    return row


def _official_first_then_latest_version(query):
    """Shared DISTINCT ON ordering for both current_projections_for_slate
    and recent_current_projections: prefer the latest genuinely official
    version (published, and not late per ADR 0008) per logical_key over a
    later evaluated-only or late-published one, falling back to the
    latest version overall when no official version exists yet for that
    key (e.g. a game still hours out with only research-stage
    evaluations logged so far).

    Without this, "current" was purely `ORDER BY version DESC` -- any
    later run, including one that happened to fire after a game's first
    pitch, would silently become the displayed record even though its
    own is_late_publication flag correctly marked it as not official.
    The flag existed but was never actually enforced anywhere; running
    the pipeline more than once a day (multiple intraday refreshes) would
    have made that gap concretely worse rather than better."""
    is_official = case(
        (and_(Projection.published_at.isnot(None), Projection.is_late_publication.is_(False)), 1),
        else_=0,
    )
    return query.order_by(Projection.logical_key, is_official.desc(), Projection.version.desc()).distinct(
        Projection.logical_key
    )


def current_projections_for_slate(session: Session, game_ids: list[str]) -> list[Projection]:
    """The latest -- preferring official, see
    _official_first_then_latest_version -- version of every projection
    for the given games. "Current" is still derived by query, never a
    mutable flag (ADR 0002)."""
    if not game_ids:
        return []
    base = select(Projection.logical_key, Projection.projection_id, Projection.version).where(
        Projection.game_id.in_(game_ids)
    )
    subq = _official_first_then_latest_version(base).subquery()
    stmt = select(Projection).join(subq, Projection.projection_id == subq.c.projection_id)
    return list(session.execute(stmt).scalars().all())


def version_history(session: Session, logical_key: str) -> list[Projection]:
    stmt = select(Projection).where(Projection.logical_key == logical_key).order_by(Projection.version.desc())
    return list(session.execute(stmt).scalars().all())


def recent_current_projections(session: Session, limit: int = 100) -> list[Projection]:
    """The latest -- preferring official -- version of every projection
    across all slates, most recently created first, for the ledger view
    when no slate_date filter is given. Same "current" derived-by-query
    pattern as current_projections_for_slate (see
    _official_first_then_latest_version), just without the game_ids
    filter."""
    base = select(Projection.logical_key, Projection.projection_id, Projection.version)
    subq = _official_first_then_latest_version(base).subquery()
    stmt = (
        select(Projection)
        .join(subq, Projection.projection_id == subq.c.projection_id)
        .order_by(Projection.created_at.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())
