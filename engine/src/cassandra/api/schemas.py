"""API response models. Deliberately thin wrappers over the ORM rows --
every field here is either a stored column or a cheap derived join
(player/team name), never a recomputation of decision/model logic (that
only ever happens in decision/engine.py and models/, never in the API
layer).
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

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


class AdminStatusResponse(BaseModel):
    sources: list[SourceHealthOut]
    recent_runs: list[PipelineRunOut]
    model_version: str
    decision_policy_version: str
    feature_set_version: str
    decision_edge_threshold: float
    git_commit_sha: str | None
    blocking_issues: list[str]


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
    line: float
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
