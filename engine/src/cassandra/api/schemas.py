"""API response models. Deliberately thin wrappers over the ORM rows --
every field here is either a stored column or a cheap derived join
(player/team name), never a recomputation of decision/model logic (that
only ever happens in decision/engine.py and models/, never in the API
layer).
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from cassandra.decision.reason_codes import describe


class ReasonCodeOut(BaseModel):
    code: str
    description: str

    @classmethod
    def from_code(cls, code: str) -> ReasonCodeOut:
        return cls(code=code, description=describe(code))


class GradeOut(BaseModel):
    result: str
    actual_strikeouts: int | None
    graded_at: datetime


class ProjectionOut(BaseModel):
    projection_id: str
    logical_key: str
    version: int
    player_id: str
    player_name: str
    team: str | None
    opponent: str | None
    game_id: str
    scheduled_start_utc: datetime
    line: float | None
    projection_mean: float | None
    projection_sd: float | None
    probability_over: float | None
    probability_under: float | None
    probability_push: float | None
    decision: str
    decision_status: str
    reason_codes: list[ReasonCodeOut]
    model_version: str | None
    feature_set_version: str | None
    decision_policy_version: str | None
    reproducibility_hash: str | None
    published_at: datetime | None
    is_late_publication: bool
    record_label: str
    grade: GradeOut | None = None
    # Recomputed from the stored probabilities (decision/engine.py's
    # edge_for_display) -- the same edge decide() used to pick OVER vs
    # UNDER, re-exposed for display since Projection doesn't persist its
    # own edge column. None only when there was never a real line.
    edge: float | None = None
    # Re-derived via the same point-in-time as-of query decide() itself
    # used at publish time (see api/assembly.py) -- which source produced
    # the line actually decided against, and how old it was as of the
    # freeze cutoff. Both null when there was no line at all.
    line_source: str | None = None
    line_observed_at: datetime | None = None
    # Plain-English "why Cassandra likes this play" / "risks to know
    # about" -- built only from stored features/probabilities/reason
    # codes (decision/explain.py), never invented after the fact. `why`
    # is always empty for a NO_PLAY -- there's nothing to like about a
    # rejected/uncertain call, only reasons, which live in `risks`.
    why: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class TodayResponse(BaseModel):
    slate_date: date
    games_count: int
    qualified_count: int
    no_play_count: int
    projections: list[ProjectionOut]


class LedgerResponse(BaseModel):
    slate_date: date | None
    entries: list[ProjectionOut]


class ProjectionHistoryResponse(BaseModel):
    logical_key: str
    versions: list[ProjectionOut]


class SourceHealthOut(BaseModel):
    source_id: str
    last_status: str | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int


class PipelineStageOut(BaseModel):
    stage: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    detail: str | None


class PipelineRunOut(BaseModel):
    run_id: str
    slate_date: date
    status: str
    current_stage: str | None
    started_at: datetime
    stages: list[PipelineStageOut]


class ActiveModelOut(BaseModel):
    """The registry artifact currently serving live predictions (Phase 4)
    -- present only when a challenger has been promoted via `cassandra
    promote-model`; the Admin page shows "permanent baseline" instead
    when this is null, since AdminStatusResponse.model_version already
    covers that case on its own."""

    artifact_id: str
    model_family: str
    fitted_model_version: str
    trained_at: datetime
    training_dataset_id: str
    training_metrics: dict
    activated_at: datetime
    activated_by: str


class PendingModelCandidateOut(BaseModel):
    """A CANDIDATE/APPROVED artifact awaiting human review -- either
    hand-registered via `cassandra train-final-model --register`, or
    produced automatically by orchestration/retraining_scheduler.py's
    "self-learning loop" (settings.auto_retrain_enabled). Never promoted
    on its own; this is purely visibility so a human knows to go look,
    per registry/service.py's promote_to_active() requiring an explicit
    human --operator action either way."""

    artifact_id: str
    model_family: str
    fitted_model_version: str
    status: str
    trained_at: datetime
    created_by: str
    training_dataset_id: str
    training_metrics: dict
    notes: str | None


class TrackerSummaryOut(BaseModel):
    """A resettable win/loss counter, not the permanent record -- the
    Ledger page already shows the full, un-resettable history. See
    grading/tracker.py's module docstring: a reset only ever records a
    new audit event, never touches a grades row (CLAUDE.md non-negotiable
    #6, "losses are never deleted")."""

    wins: int
    losses: int
    pushes: int
    voids: int
    no_plays: int
    win_rate: float | None
    tracker_started_at: datetime
    last_reset_by: str | None


class ScoreboardWindowOut(BaseModel):
    """One time window of the LIVE-only track record (grading/
    scoreboard.py) -- strictly never mixes in DEMO/BACKTEST/PAPER/SHADOW
    results."""

    wins: int
    losses: int
    pushes: int
    voids: int
    no_plays: int
    waiting: int
    win_rate: float | None
    mean_absolute_error: float | None
    projection_error_sample_size: int


class ScoreboardOut(BaseModel):
    as_of: datetime
    today: ScoreboardWindowOut
    last_7_days: ScoreboardWindowOut
    last_30_days: ScoreboardWindowOut
    all_time: ScoreboardWindowOut


class AdminStatusResponse(BaseModel):
    sources: list[SourceHealthOut]
    recent_runs: list[PipelineRunOut]
    model_version: str
    decision_policy_version: str
    feature_set_version: str
    decision_edge_threshold: float
    git_commit_sha: str | None
    # Null whenever no artifact is ACTIVE -- model_version above already
    # reads as the permanent baseline's version string in that case, this
    # is the richer detail (training provenance/metrics/who-activated-it)
    # only a real promoted artifact has.
    active_model: ActiveModelOut | None
    # CANDIDATE/APPROVED artifacts not yet promoted or rejected -- empty
    # list in the common case (nothing pending review).
    pending_model_candidates: list[PendingModelCandidateOut]
    tracker: TrackerSummaryOut
    scoreboard: ScoreboardOut
    blocking_issues: list[str]
    # System-snapshot strip: real counts for "today" (ADR 0009 operating
    # tz), computed via the exact same query GET /api/today uses -- never
    # a separate/divergent number. See admin.py's _today_summary().
    today_slate_date: date
    today_games_count: int
    today_qualified_count: int
    today_no_play_count: int
    # A real row count from the historical backfill subsystem -- purely
    # informational (never fed into the live pipeline itself; see
    # admin.py's _historical_training_rows()).
    historical_training_rows: int
    # Real scheduler configuration (config.py's settings) -- what Cassandra
    # will actually do next, not a guess. auto_run_hours_local is the raw
    # configured string (e.g. "7,12,16"); the Admin UI formats it.
    auto_scheduler_enabled: bool
    auto_run_hours_local: str
    auto_retrain_enabled: bool


class RunActionResponse(BaseModel):
    run_id: str
    slate_date: date
    entries_frozen: int
    entries_skipped_no_starter: int
    projections_published: int
    ingest_warnings: list[str]


class GradeActionResponse(BaseModel):
    run_id: str
    slate_date: date
    grades_written: int


class LineImportEntryIn(BaseModel):
    player_name: str
    # Bounded well outside any real MLB single-game strikeout total (the
    # modern record is ~20) -- found by an independent security review:
    # an unbounded line reaches PoissonStrikeoutDistribution.cdf()'s O(k)
    # loop (decision/engine.py's `math.floor(line)`), so a malformed/
    # malicious extreme value could otherwise hang a request thread.
    # Rejected here with a clear 422, not silently clamped.
    line: float = Field(gt=-1, lt=100)
    over_price: float | None = None
    under_price: float | None = None
    market: str = "pitcher_strikeouts"


class MatchedLineImportEntryOut(BaseModel):
    player_name: str
    line: float
    over_price: float | None
    under_price: float | None
    market: str
    player_mlb_id: int
    mlb_game_pk: int
    is_possible_duplicate: bool


class UnmatchedLineImportEntryOut(BaseModel):
    player_name: str
    line: float
    market: str
    reason: str


class LineImportPreviewResponse(BaseModel):
    slate_date: date
    matched: list[MatchedLineImportEntryOut]
    unmatched: list[UnmatchedLineImportEntryOut]


class LineImportCommitResponse(BaseModel):
    slate_date: date
    records_written: int
    not_imported: list[str]
