# ADR 0007 — Pipeline action state guards

**Status:** Decided (partially implemented — see below, not stale)

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

Partially implemented, accurately reflected in `api/routers/admin.py`'s
own docstring (which this ADR's status line should have been kept in
sync with). The admin action endpoints now exist
(`POST /api/admin/runs/{slate_date}/{run,grade}`), mapping directly to
what `orchestration/run_slate.py` actually has — but only `run` (the
full INGEST→PUBLISH chain, one atomic call) and `grade`, not the richer
`revalidate`/`regenerate`/`publish` split with the specific per-action
guards this ADR describes. The `pipeline_run_stages` schema this ADR
called for is built and populated by every real run, so those guards
have something authoritative to check against whenever the fuller
action split is built.
