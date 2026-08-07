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

from cassandra.api.deps import get_db, require_admin
from cassandra.api.schemas import (
    AdminStatusResponse,
    GradeActionResponse,
    LineImportCommitResponse,
    LineImportEntryIn,
    LineImportPreviewResponse,
    MatchedLineImportEntryOut,
    PipelineRunOut,
    PipelineStageOut,
    RunActionResponse,
    SourceHealthOut,
    UnmatchedLineImportEntryOut,
)
from cassandra.config import get_git_commit_sha, settings
from cassandra.db.models.pipeline import PipelineRun, PipelineRunStage
from cassandra.db.models.sources import SourceHealth
from cassandra.decision.engine import DECISION_POLICY_VERSION
from cassandra.features.builders import FEATURE_SET_VERSION
from cassandra.ingestion.manual_line_import import LineImportEntry, commit_line_import, preview_line_import
from cassandra.models.baseline import MODEL_VERSION
from cassandra.orchestration.run_slate import grade_slate_run, run_slate

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

CONSECUTIVE_FAILURE_ALERT_THRESHOLD = 3
RECENT_RUNS_LIMIT = 10
# Source-health states that are never a blocking issue regardless of
# consecutive_failures -- see db/models/sources.py's SOURCE_HEALTH_STATES
# for what each means. DISABLED (e.g. umpire_stub, a permanent by-design
# stub) and PENDING/QUOTA_LIMITED (expected, temporary, or a known vendor
# limit, not "something is broken") would otherwise be a standing false
# alarm an operator could never actually resolve. Superseded the earlier
# hardcoded-by-adapter-name NEVER_BLOCKING_SOURCES set -- this is the
# general mechanism that set was a special case of.
NEVER_BLOCKING_STATES = {"DISABLED", "PENDING", "QUOTA_LIMITED"}


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
        if s.last_status in NEVER_BLOCKING_STATES:
            continue
        if s.consecutive_failures >= CONSECUTIVE_FAILURE_ALERT_THRESHOLD:
            blocking_issues.append(f"Source {s.source_id} has failed {s.consecutive_failures} times in a row")

    git_commit_sha = get_git_commit_sha()
    if git_commit_sha is None:
        # Phase 2B: a missing deployed commit SHA must be a visible
        # warning, not a silent gap -- otherwise an operator has no way
        # to confirm which code a given projection/run actually came
        # from. Surfaced via blocking_issues since that's the only
        # existing "make this visible to the operator" channel; see
        # config.py's get_git_commit_sha() for how GIT_COMMIT_SHA/`git
        # rev-parse HEAD` are resolved.
        blocking_issues.append(
            "No git commit SHA available -- set the GIT_COMMIT_SHA environment "
            "variable at deploy time (no .git directory to introspect on Replit)"
        )

    return AdminStatusResponse(
        sources=source_outs,
        recent_runs=run_outs,
        model_version=MODEL_VERSION,
        decision_policy_version=DECISION_POLICY_VERSION,
        feature_set_version=FEATURE_SET_VERSION,
        decision_edge_threshold=settings.decision_edge_threshold,
        git_commit_sha=git_commit_sha,
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


def _to_entries(entries_in: list[LineImportEntryIn]) -> list[LineImportEntry]:
    return [
        LineImportEntry(
            player_name=e.player_name,
            line=e.line,
            over_price=e.over_price,
            under_price=e.under_price,
            market=e.market,
        )
        for e in entries_in
    ]


@router.post("/lines/{slate_date}/preview", response_model=LineImportPreviewResponse)
def preview_lines(
    slate_date: date_type,
    entries: list[LineImportEntryIn] = Body(embed=True),
    db: Session = Depends(get_db),
) -> LineImportPreviewResponse:
    """Resolves pasted lines against today's real confirmed starters
    without writing anything -- see ingestion/manual_line_import.py.
    Call this before `/lines/{slate_date}/import` so an operator can see
    exactly what will and won't be imported."""
    preview = preview_line_import(db, slate_date, _to_entries(entries))
    return LineImportPreviewResponse(
        slate_date=slate_date,
        matched=[
            MatchedLineImportEntryOut(
                player_name=m.entry.player_name,
                line=m.entry.line,
                over_price=m.entry.over_price,
                under_price=m.entry.under_price,
                market=m.entry.market,
                player_mlb_id=m.player_mlb_id,
                mlb_game_pk=m.mlb_game_pk,
                is_possible_duplicate=m.is_possible_duplicate,
            )
            for m in preview.matched
        ],
        unmatched=[
            UnmatchedLineImportEntryOut(
                player_name=u.entry.player_name, line=u.entry.line, market=u.entry.market, reason=u.reason
            )
            for u in preview.unmatched
        ],
    )


@router.post("/lines/{slate_date}/import", response_model=LineImportCommitResponse)
def import_lines(
    slate_date: date_type,
    entries: list[LineImportEntryIn] = Body(embed=True),
    db: Session = Depends(get_db),
) -> LineImportCommitResponse:
    """Writes matched entries as real `raw_lines` rows (append-only, same
    contract every other lines adapter produces). Unmatched entries are
    never written or guessed at -- see `not_imported` for exactly what
    didn't match and why."""
    result = commit_line_import(db, slate_date, _to_entries(entries))
    return LineImportCommitResponse(
        slate_date=slate_date, records_written=result.records_written, not_imported=result.warnings
    )
