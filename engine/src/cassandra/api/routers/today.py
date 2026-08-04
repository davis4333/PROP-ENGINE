"""GET /api/today -- every evaluated projection for a slate, not just
qualified picks (the handbook's transparency requirement). Defaults to
today in the operating timezone (ADR 0009)."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from cassandra.api.assembly import assemble_projection_out
from cassandra.api.deps import get_db
from cassandra.api.schemas import TodayResponse
from cassandra.config import operating_tz
from cassandra.grading.service import current_grades_for_projections
from cassandra.ledger.service import current_projections_for_slate
from cassandra.pit.snapshot_builder import games_for_slate_date

router = APIRouter(prefix="/api/today", tags=["today"])


@router.get("", response_model=TodayResponse)
def get_today(
    slate_date: date_type | None = Query(
        default=None, description="Defaults to today (ADR 0009 operating tz)."
    ),
    db: Session = Depends(get_db),
) -> TodayResponse:
    resolved_date = slate_date or datetime.now(operating_tz()).date()
    games = games_for_slate_date(db, resolved_date)
    projections = current_projections_for_slate(db, [g.game_id for g in games])
    grades = current_grades_for_projections(db, [p.projection_id for p in projections])
    grades_by_projection = {g.projection_id: g for g in grades}

    outs = [assemble_projection_out(db, p, grades_by_projection.get(p.projection_id)) for p in projections]
    outs.sort(key=lambda o: o.scheduled_start_utc)

    return TodayResponse(
        slate_date=resolved_date,
        games_count=len(games),
        qualified_count=sum(1 for o in outs if o.decision_status == "QUALIFIED"),
        no_play_count=sum(1 for o in outs if o.decision == "NO_PLAY"),
        projections=outs,
    )
