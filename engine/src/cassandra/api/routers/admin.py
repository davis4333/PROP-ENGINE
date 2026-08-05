"""Admin: source health, pipeline stage tracker, and the two implemented
run actions (`run`, `grade`). Gated by ADR 0011's shared-secret header --
explicitly a demo-only placeholder, not production auth.

ADR 0007 describes a richer revalidate/regenerate/publish/grade action
split with state guards; that ADR's own "Status" section marks it "Not
yet implemented" pending Phase 4. This MVP implements the two actions
that map directly to what orchestration/run_slate.py actually has:
running a slate (ingest through publish, one atomic call) and grading a
slate. See CURRENT_STATE_AUDIT.md.
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as date_type

from fastapi import APIRouter, Body, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from cassandra.adapters.umpire_stub import UmpireStubAdapter
from cassandra.api.deps import get_db, require_admin
from cassandra.api.schemas import (
    AdminStatusResponse,
    GradeActionResponse,
    PipelineRunOut,
    PipelineStageOut,
    RunActionResponse,
    SourceHealthOut,
)
from cassandra.config import settings
from cassandra.db.models.pipeline import PipelineRun, PipelineRunStage
from cassandra.db.models.sources import SourceHealth
from cassandra.decision.engine import DECISION_POLICY_VERSION
from cassandra.features.builders import FEATURE_SET_VERSION
from cassandra.models.baseline import MODEL_VERSION
from cassandra.orchestration.run_slate import grade_slate_run, run_slate

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

CONSECUTIVE_FAILURE_ALERT_THRESHOLD = 3
RECENT_RUNS_LIMIT = 10
# umpire_stub is a permanent stand-in -- no reliable free umpire source
# exists, so it reports unavailable on every single call by design (see
# its own docstring and CURRENT_STATE_AUDIT.md's Provisional section).
# The handbook is explicit that this must never block or alarm anything;
# surfacing it here as a "blocking issue" would be a standing false
# alarm an operator could never actually resolve.
NEVER_BLOCKING_SOURCES = {UmpireStubAdapter.source_name}


@router.get("/status", response_model=AdminStatusResponse)
def get_admin_status(db: Session = Depends(get_db)) -> AdminStatusResponse:
    sources = db.execute(select(SourceHealth)).scalars().all()
    runs = (
        db.execute(select(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(RECENT_RUNS_LIMIT))
        .scalars()
        .all()
    )

    blocking_issues: list[str] = []
    run_outs: list[PipelineRunOut] = []
    for run in runs:
        stages = (
            db.execute(
                select(PipelineRunStage)
                .where(PipelineRunStage.run_id == run.run_id)
                .order_by(PipelineRunStage.stage)
            )
            .scalars()
            .all()
        )
        run_outs.append(
            PipelineRunOut(
                run_id=run.run_id,
                slate_date=run.slate_date,
                status=run.status,
                current_stage=run.current_stage,
                started_at=run.started_at,
                stages=[
                    PipelineStageOut(
                        stage=s.stage,
                        status=s.status,
                        started_at=s.started_at,
                        finished_at=s.finished_at,
                        detail=s.detail,
                    )
                    for s in stages
                ],
            )
        )
        if run.status == "failed":
            blocking_issues.append(f"Run {run.run_id} ({run.slate_date}) failed at stage {run.current_stage}")

    source_outs = [
        SourceHealthOut(
            source_id=s.source_id,
            last_status=s.last_status,
            last_success_at=s.last_success_at,
            last_failure_at=s.last_failure_at,
            consecutive_failures=s.consecutive_failures,
        )
        for s in sources
    ]
    for s in sources:
        if s.source_id in NEVER_BLOCKING_SOURCES:
            continue
        if s.consecutive_failures >= CONSECUTIVE_FAILURE_ALERT_THRESHOLD:
            blocking_issues.append(f"Source {s.source_id} has failed {s.consecutive_failures} times in a row")

    return AdminStatusResponse(
        sources=source_outs,
        recent_runs=run_outs,
        model_version=MODEL_VERSION,
        decision_policy_version=DECISION_POLICY_VERSION,
        feature_set_version=FEATURE_SET_VERSION,
        decision_edge_threshold=settings.decision_edge_threshold,
        blocking_issues=blocking_issues,
    )


@router.post("/runs/{slate_date}/run", response_model=RunActionResponse)
def trigger_run(
    slate_date: date_type,
    cutoff_at: datetime | None = Body(default=None, embed=True),
    db: Session = Depends(get_db),
) -> RunActionResponse:
    resolved_cutoff = cutoff_at or datetime.now(UTC)
    if resolved_cutoff.tzinfo is None:
        resolved_cutoff = resolved_cutoff.replace(tzinfo=UTC)
    result = run_slate(db, slate_date, resolved_cutoff)
    ingest_warnings = [w for r in result.ingest_results for w in r.warnings]
    return RunActionResponse(
        run_id=result.run_id,
        slate_date=result.slate_date,
        entries_frozen=result.entries_frozen,
        entries_skipped_no_starter=result.entries_skipped_no_starter,
        projections_published=len(result.projections_published),
        ingest_warnings=ingest_warnings,
    )


@router.post("/runs/{slate_date}/grade", response_model=GradeActionResponse)
def trigger_grade(slate_date: date_type, db: Session = Depends(get_db)) -> GradeActionResponse:
    result = grade_slate_run(db, slate_date)
    return GradeActionResponse(
        run_id=result.run_id, slate_date=result.slate_date, grades_written=len(result.grades)
    )
