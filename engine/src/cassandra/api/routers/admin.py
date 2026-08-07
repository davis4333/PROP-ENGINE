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
    ActiveModelOut,
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
from cassandra.db.models.registry import ModelArtifact, ModelRegistryEvent
from cassandra.db.models.sources import SourceHealth
from cassandra.decision.engine import DECISION_POLICY_VERSION
from cassandra.features.builders import FEATURE_SET_VERSION
from cassandra.ingestion.manual_line_import import LineImportEntry, commit_line_import, preview_line_import
from cassandra.orchestration.run_slate import grade_slate_run, run_slate
from cassandra.registry.service import resolve_active_model

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

    resolved_model = resolve_active_model(db)
    active_model_out: ActiveModelOut | None = None
    if resolved_model.active_artifact_id is not None:
        artifact = db.get(ModelArtifact, resolved_model.active_artifact_id)
        if artifact is None:
            raise RuntimeError(
                f"active_artifact_id={resolved_model.active_artifact_id} but no matching row exists -- "
                "should be structurally impossible (model_artifacts is append-only)"
            )
        # active_artifact()'s own contract guarantees this artifact's
        # latest event is the ACTIVE one -- reading it back here gives
        # "when/by whom" without resolve_active_model() needing to widen
        # its own return type just to carry this Admin-only detail.
        latest_event = db.execute(
            select(ModelRegistryEvent)
            .where(ModelRegistryEvent.artifact_id == resolved_model.active_artifact_id)
            .order_by(ModelRegistryEvent.sequence.desc())
            .limit(1)
        ).scalar_one()
        active_model_out = ActiveModelOut(
            artifact_id=artifact.artifact_id,
            model_family=artifact.model_family,
            fitted_model_version=artifact.fitted_model_version,
            trained_at=artifact.trained_at,
            training_dataset_id=artifact.training_dataset_id,
            training_metrics=artifact.training_metrics,
            activated_at=latest_event.occurred_at,
            activated_by=latest_event.operator,
        )

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
        # The REAL model_version run_slate() would use right now -- the
        # active artifact's fitted_model_version if one is promoted,
        # otherwise the permanent baseline's, via the exact same
        # resolve_active_model() run_slate() itself calls (Phase 4).
        # Previously always the hardcoded baseline constant, which would
        # have been stale/wrong the moment any challenger was promoted.
        model_version=resolved_model.model_version,
        decision_policy_version=DECISION_POLICY_VERSION,
        feature_set_version=FEATURE_SET_VERSION,
        decision_edge_threshold=settings.decision_edge_threshold,
        git_commit_sha=git_commit_sha,
        active_model=active_model_out,
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
