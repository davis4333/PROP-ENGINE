"""Honest, append-only grading (ADR 0007: a grade requires PUBLISH to have
succeeded for that projection and the game to be Final). Never UPDATEs a
`grades` row -- a correction (e.g. an official scorer revision) inserts a
new row with a later `graded_at`; "current" grade = latest `graded_at` per
`projection_id`, the same derived-by-query pattern as ledger/service.py.
Losses are never deleted (CLAUDE.md non-negotiable #6).

Per CLAUDE.md's do-not-do list: this is the only module that reads
`raw_final_box_scores`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from cassandra.db.models.audit import AuditEvent
from cassandra.db.models.grading import Grade
from cassandra.db.models.identity import Game, Player
from cassandra.db.models.projection import Projection
from cassandra.db.models.raw import RawFinalBoxScore

FINAL_STATUS = "Final"


def latest_final_box_score(session: Session, mlb_game_pk: int, player_mlb_id: int) -> RawFinalBoxScore | None:
    """The freshest Final box score row for a pitcher's outing in a game --
    never considers a non-Final row, even one ingested more recently (ADR
    0007). A correction to a Final outing is a new, later-ingested row;
    this always returns the newest one."""
    stmt = (
        select(RawFinalBoxScore)
        .where(
            RawFinalBoxScore.mlb_game_pk == mlb_game_pk,
            RawFinalBoxScore.player_mlb_id == player_mlb_id,
            RawFinalBoxScore.game_status == FINAL_STATUS,
        )
        .order_by(RawFinalBoxScore.ingested_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalars().first()


def _grade_result(decision: str, line: Decimal | float | None, actual: int | None) -> str:
    if decision == "NO_PLAY":
        return "NO_PLAY"
    if actual is None or line is None:
        # Final box score exists but has no usable stat (e.g. a scratched
        # start) or the projection carried no line -- neither side of the
        # bet can be evaluated.
        return "VOID"
    actual_d = Decimal(actual)
    line_d = Decimal(str(line))
    if decision == "OVER":
        if actual_d > line_d:
            return "WIN"
        if actual_d < line_d:
            return "LOSS"
        return "PUSH"
    if decision == "UNDER":
        if actual_d < line_d:
            return "WIN"
        if actual_d > line_d:
            return "LOSS"
        return "PUSH"
    raise ValueError(f"unknown decision: {decision!r}")


def current_grade_for_projection(session: Session, projection_id: str) -> Grade | None:
    stmt = select(Grade).where(Grade.projection_id == projection_id).order_by(Grade.graded_at.desc()).limit(1)
    return session.execute(stmt).scalars().first()


def grade_projection(session: Session, projection: Projection, run_id: str) -> Grade | None:
    """Writes one append-only grade row for a single projection. Returns
    None (no write) when grading isn't possible yet: the projection was
    never published (ADR 0007), its game/player identity can't be
    resolved, or no Final box score exists yet for that pitcher's outing
    -- none of these are errors, all are "not gradeable yet".

    If a current grade already exists and points at the same Final box
    score row, nothing changed since the last grading pass, so no
    duplicate row is written -- the existing grade is returned as-is.
    """
    if projection.published_at is None:
        return None

    game = session.get(Game, projection.game_id)
    player = session.get(Player, projection.player_id)
    if game is None or game.mlb_game_pk is None or player is None or player.mlb_person_id is None:
        return None

    box = latest_final_box_score(session, game.mlb_game_pk, player.mlb_person_id)
    if box is None:
        return None

    existing = current_grade_for_projection(session, projection.projection_id)
    if existing is not None and existing.final_box_score_raw_id == box.raw_id:
        return existing

    actual = box.strikeouts_recorded
    result = _grade_result(projection.decision, projection.line, actual)

    row = Grade(
        grade_id=uuid.uuid4(),
        projection_id=projection.projection_id,
        graded_at=datetime.now(UTC),
        result=result,
        actual_strikeouts=actual,
        final_box_score_raw_id=box.raw_id,
        detail=None if actual is not None else "Final box score has no strikeouts_recorded",
    )
    session.add(row)
    session.add(
        AuditEvent(
            event_type="GRADE",
            entity_type="projection",
            entity_id=projection.projection_id,
            run_id=run_id,
            payload={
                "grade_id": str(row.grade_id),
                "result": result,
                "actual_strikeouts": actual,
                "final_box_score_raw_id": str(box.raw_id),
                "is_correction": existing is not None,
            },
        )
    )
    return row


def grade_slate(session: Session, projections: list[Projection], run_id: str) -> list[Grade]:
    """Grades every gradeable projection in the given list (typically the
    "current" projections for a slate from
    ledger.current_projections_for_slate). Partial grading is expected and
    fine -- some games in a slate are Final while others aren't yet (ADR
    0007); projections whose game isn't Final are silently skipped, not an
    error."""
    graded = []
    for projection in projections:
        grade = grade_projection(session, projection, run_id)
        if grade is not None:
            graded.append(grade)
    return graded


def current_grades_for_projections(session: Session, projection_ids: list[str]) -> list[Grade]:
    """The latest grade per projection_id -- "current" derived by query,
    same pattern as ledger.current_projections_for_slate."""
    if not projection_ids:
        return []
    subq = (
        select(Grade.projection_id, Grade.grade_id, Grade.graded_at)
        .where(Grade.projection_id.in_(projection_ids))
        .order_by(Grade.projection_id, Grade.graded_at.desc())
        .distinct(Grade.projection_id)
        .subquery()
    )
    stmt = select(Grade).join(subq, Grade.grade_id == subq.c.grade_id)
    return list(session.execute(stmt).scalars().all())
