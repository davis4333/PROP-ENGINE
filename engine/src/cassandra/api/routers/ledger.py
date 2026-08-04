"""GET /api/ledger -- the honest results ledger. Every evaluated
projection with its grade (win/loss/push/void/no-play) if graded yet --
losses are never hidden or filtered out (CLAUDE.md non-negotiable #6)."""

from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from cassandra.api.assembly import assemble_projection_out
from cassandra.api.deps import get_db
from cassandra.api.schemas import LedgerResponse, ProjectionHistoryResponse
from cassandra.db.models.projection import Projection
from cassandra.grading.service import current_grades_for_projections
from cassandra.ledger.service import (
    current_projections_for_slate,
    recent_current_projections,
    version_history,
)
from cassandra.pit.snapshot_builder import games_for_slate_date

router = APIRouter(prefix="/api/ledger", tags=["ledger"])


@router.get("", response_model=LedgerResponse)
def get_ledger(
    slate_date: date_type | None = Query(
        default=None, description="Omit for the most recent entries overall."
    ),
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
) -> LedgerResponse:
    if slate_date is not None:
        games = games_for_slate_date(db, slate_date)
        projections = current_projections_for_slate(db, [g.game_id for g in games])
    else:
        projections = recent_current_projections(db, limit=limit)

    grades = current_grades_for_projections(db, [p.projection_id for p in projections])
    grades_by_projection = {g.projection_id: g for g in grades}
    entries = [assemble_projection_out(db, p, grades_by_projection.get(p.projection_id)) for p in projections]
    entries.sort(key=lambda o: o.scheduled_start_utc, reverse=True)

    return LedgerResponse(slate_date=slate_date, entries=entries)


@router.get("/{projection_id}", response_model=ProjectionHistoryResponse)
def get_projection_history(projection_id: str, db: Session = Depends(get_db)) -> ProjectionHistoryResponse:
    projection = db.get(Projection, projection_id)
    if projection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projection not found")

    history = version_history(db, projection.logical_key)
    grades = current_grades_for_projections(db, [p.projection_id for p in history])
    grades_by_projection = {g.projection_id: g for g in grades}
    versions = [assemble_projection_out(db, p, grades_by_projection.get(p.projection_id)) for p in history]

    return ProjectionHistoryResponse(logical_key=projection.logical_key, versions=versions)
