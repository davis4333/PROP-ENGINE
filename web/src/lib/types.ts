/** Mirrors engine/src/cassandra/api/schemas.py -- keep in sync by hand;
 * there is no shared schema generation for this vertical slice. */

export interface ReasonCodeOut {
  code: string;
  description: string;
}

export interface GradeOut {
  result: "WIN" | "LOSS" | "PUSH" | "VOID" | "NO_PLAY";
  actual_strikeouts: number | null;
  graded_at: string;
}

export interface ProjectionOut {
  projection_id: string;
  logical_key: string;
  version: number;
  player_id: string;
  player_name: string;
  team: string | null;
  opponent: string | null;
  game_id: string;
  scheduled_start_utc: string;
  line: number | null;
  projection_mean: number | null;
  projection_sd: number | null;
  probability_over: number | null;
  probability_under: number | null;
  probability_push: number | null;
  decision: "OVER" | "UNDER" | "NO_PLAY";
  decision_status: "QUALIFIED" | "UNCERTAIN" | "HELD" | "REJECTED";
  reason_codes: ReasonCodeOut[];
  model_version: string | null;
  feature_set_version: string | null;
  decision_policy_version: string | null;
  reproducibility_hash: string | null;
  published_at: string | null;
  is_late_publication: boolean;
  record_label: string;
  grade: GradeOut | null;
}

export interface TodayResponse {
  slate_date: string;
  games_count: number;
  qualified_count: number;
  no_play_count: number;
  projections: ProjectionOut[];
}

export interface LedgerResponse {
  slate_date: string | null;
  entries: ProjectionOut[];
}

export interface ProjectionHistoryResponse {
  logical_key: string;
  versions: ProjectionOut[];
}

export interface SourceHealthOut {
  source_id: string;
  last_status: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  consecutive_failures: number;
}

export interface PipelineStageOut {
  stage: string;
  status: "pending" | "running" | "succeeded" | "failed" | "skipped";
  started_at: string | null;
  finished_at: string | null;
  detail: string | null;
}

export interface PipelineRunOut {
  run_id: string;
  slate_date: string;
  status: "running" | "succeeded" | "failed";
  current_stage: string | null;
  started_at: string;
  stages: PipelineStageOut[];
}

export interface AdminStatusResponse {
  sources: SourceHealthOut[];
  recent_runs: PipelineRunOut[];
  model_version: string;
  decision_policy_version: string;
  feature_set_version: string;
  decision_edge_threshold: number;
  blocking_issues: string[];
}

export interface RunActionResponse {
  run_id: string;
  slate_date: string;
  entries_frozen: number;
  entries_skipped_no_starter: number;
  projections_published: number;
  ingest_warnings: string[];
}

export interface GradeActionResponse {
  run_id: string;
  slate_date: string;
  grades_written: number;
}

export interface LineImportEntryIn {
  player_name: string;
  line: number;
  over_price?: number | null;
  under_price?: number | null;
  market?: string;
}

export interface MatchedLineImportEntryOut {
  player_name: string;
  line: number;
  over_price: number | null;
  under_price: number | null;
  market: string;
  player_mlb_id: number;
  mlb_game_pk: number;
  is_possible_duplicate: boolean;
}

export interface UnmatchedLineImportEntryOut {
  player_name: string;
  line: number;
  market: string;
  reason: string;
}

export interface LineImportPreviewResponse {
  slate_date: string;
  matched: MatchedLineImportEntryOut[];
  unmatched: UnmatchedLineImportEntryOut[];
}

export interface LineImportCommitResponse {
  slate_date: string;
  records_written: number;
  not_imported: string[];
}
