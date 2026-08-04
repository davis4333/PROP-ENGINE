"""The append-only projection ledger writer. Never UPDATEs a `projections`
row -- see CLAUDE.md's do-not-do list and ADR 0002. "Current" is always
derived by query (`current_projections_for_slate` /
`current_projection_versions`), never by a mutable flag.

Publication is a distinct concept from being evaluated or qualified
(ADR 0002): every call here writes a row (the full transparency record),
but only `publish=True` calls set `published_at`. A projection published
after its game's scheduled start is labeled `is_late_publication=True`
(ADR 0008) and must be excluded from official public performance
aggregates by readers, not by hiding the row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
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
    is_late = bool(published_at and game.scheduled_start_utc and published_at > game.scheduled_start_utc)

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


def current_projections_for_slate(session: Session, game_ids: list[str]) -> list[Projection]:
    """The latest version of every projection for the given games --
    "current" derived by query, never by a mutable flag (ADR 0002)."""
    if not game_ids:
        return []
    subq = (
        select(
            Projection.logical_key,
            Projection.projection_id,
            Projection.version,
        )
        .where(Projection.game_id.in_(game_ids))
        .order_by(Projection.logical_key, Projection.version.desc())
        .distinct(Projection.logical_key)
        .subquery()
    )
    stmt = select(Projection).join(subq, Projection.projection_id == subq.c.projection_id)
    return list(session.execute(stmt).scalars().all())


def version_history(session: Session, logical_key: str) -> list[Projection]:
    stmt = select(Projection).where(Projection.logical_key == logical_key).order_by(Projection.version.desc())
    return list(session.execute(stmt).scalars().all())
