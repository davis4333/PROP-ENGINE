# ADR 0007 — Pipeline action state guards

**Status:** Decided (design constraint for Phase 4, not yet implemented)

## Decision

`pipeline_runs`/`pipeline_run_stages` (Phase 1 schema) model the ordered
stage sequence INGEST → VALIDATE → FREEZE → PROJECT → REVIEW → PUBLISH →
GRADE. The admin action endpoints built in Phase 4
(`POST /api/admin/runs/{slate_date}/{revalidate|regenerate|publish|grade}`)
must enforce strict state guards, not just call the underlying service
functions directly:

- `regenerate` is only valid on a run that has not yet been `PUBLISH`ed
  (publishing is the immutability boundary — see ADR 0002's
  evaluated/qualified/published distinction). Regenerating a published run
  must create a new run/snapshot/projection version, never touch the
  published rows.
- `publish` requires `REVIEW` to have `succeeded` for that run; it cannot
  be called on a run stuck at `FREEZE` or `PROJECT`.
- `grade` requires `PUBLISH` to have `succeeded` and requires the
  underlying `raw_final_box_scores` rows to have `game_status = 'Final'`
  (already true structurally per ADR 0001) for every game in the slate
  being graded — partial grading of a slate is allowed (some games Final,
  others not), but each individual grade write checks its own game.
- Any guard violation returns a 409-style structured error naming the
  actual current stage/status, not a generic failure.

## Status

Not yet implemented — Phase 1 (Foundation) only, since the admin action
endpoints themselves are Phase 4 work. The `pipeline_run_stages` schema is
built now specifically so these guards have something authoritative to
check against later.
