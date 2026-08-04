---
name: cassandra-ledger-integrity
description: Verify immutability invariants across the projection ledger, grading, raw ingestion, and audit tables — no UPDATE/DELETE against raw_*/projections/grades/audit_events, "current" always derived by query rather than a mutable flag, append-only grade corrections, publication-cutoff/late-publication labeling (ADR 0008), and pipeline state guards (ADR 0007) before regenerate/publish/grade actions. Use when reviewing changes to ledger/service.py, grading/service.py, admin action endpoints, orchestration/run_slate.py, or any migration touching raw_*/projections/grades/audit_events.
---

# Cassandra ledger immutability audit

The append-only ledger is a core non-negotiable (`CLAUDE.md` #3, #6). This
skill checks that immutability holds structurally, not just by convention.

## 1. No UPDATE/DELETE against the protected tables

Protected tables: every `raw_*` table (`db/models/raw.py`),
`projections`, `grades`, `audit_events`. The initial Alembic migration
`REVOKE`s `UPDATE`/`DELETE` on these for the application DB role — that is
the actual enforcement mechanism, not a lint rule. When reviewing:

- Grep the diff for `.update(`, `UPDATE `, `.delete(`, `DELETE FROM`
  against any ORM model in `db/models/raw.py`, `Projection`, `Grade`, or
  `AuditEvent`, or their table names in raw SQL/Alembic migrations.
- If a migration touches the grants (`REVOKE`/`GRANT` statements) on these
  tables, that is itself a red flag requiring explicit justification — the
  whole design assumes these grants never get loosened.
- If new application code "needs" an UPDATE on one of these tables, the
  correct fix is a new append-only row (new version, new grade, new audit
  event) — per `CLAUDE.md`: "if a query needs an UPDATE there, the design
  is wrong, not the grant." Flag this as a design problem, not something to
  patch around with a broader grant.

## 2. No `is_current` / mutable-flag columns

Per `CLAUDE.md`'s do-not-do list and the module docstring in
`db/models/projection.py`: never add an `is_current` (or similarly named)
mutable flag to `projections` or `grades`. "Current" is always derived:

- Projections: `SELECT DISTINCT ON (logical_key) * FROM projections ORDER BY logical_key, version DESC`
  — driven by `logical_key` + `version` + `supersedes_projection_id`, not a
  flag flip.
- Grades: latest `graded_at` per `projection_id` — a correction is a new
  `grades` row with a later `graded_at`, old rows (including old losses)
  stay queryable forever.

Reject any schema change or query helper that introduces a boolean
"current"/"active"/"latest" column backed by a mutation — this makes the
immutability guarantee false even if the underlying rows are never
UPDATEd, because "which row counts" would then be a mutable fact.

## 3. Grade corrections are append-only

Check `grading/service.py` (or wherever grade-writing logic lives): a
correction must always be a new `INSERT` into `grades` with the current
timestamp as `graded_at`, referencing the same `projection_id` and the
correct `final_box_score_raw_id`. Never a rewrite of the prior row. Verify
losses specifically are never deleted or hidden — `CLAUDE.md` #6 and the
handbook's honest-grading principle require the full win/loss/push/void
history to remain queryable, precisely so a bad day can't be quietly
erased.

## 4. Publication cutoff / late-publication labeling (ADR 0008)

Per `docs/adr/0008-publication-cutoff-rule.md`, a projection only counts
toward the official public performance record if `published_at` is before
the game's `scheduled_start_utc`. Check:

- Any publish path sets `projections.is_late_publication = true` when
  `published_at >= games.scheduled_start_utc` for that row's game — never
  silently drops or refuses the write (nothing is ever deleted).
- Ledger/aggregate queries (public performance stats, Ledger page data)
  filter `is_late_publication = false` (in addition to `published_at IS
  NOT NULL`) when computing official win/loss/qualified-play track
  records — but the full evaluated-record view still shows late rows,
  clearly labeled, for transparency.
- A late row is never quietly folded into the headline record — that's
  exactly the "rerun projection padding the public track record after the
  fact" failure mode ADR 0008 exists to prevent.

## 5. Pipeline state guards before regenerate/publish/grade (ADR 0007)

Per `docs/adr/0007-pipeline-state-guards.md`, the admin action endpoints
(`POST /api/admin/runs/{slate_date}/{revalidate|regenerate|publish|grade}`)
must enforce, against `pipeline_runs`/`pipeline_run_stages`
(`db/models/pipeline.py`), not just call the underlying service:

- `regenerate` — only valid on a run **not yet `PUBLISH`ed**. Regenerating
  a published run must create a new run/snapshot/projection version
  (`supersedes_projection_id` set), never touch the published rows.
- `publish` — requires the `REVIEW` stage to have `status = 'succeeded'`
  for that run. Cannot be called from `FREEZE` or `PROJECT`.
- `grade` — requires `PUBLISH` to have `succeeded`, and requires
  `raw_final_box_scores.game_status = 'Final'` for each game being graded,
  checked per-game (partial grading of a slate — some games Final, others
  not — is allowed).
- Any guard violation returns a structured 409-style error naming the
  actual current stage/status, never a generic failure.

When reviewing an admin action endpoint or `orchestration/run_slate.py`
change, trace the guard check explicitly against `pipeline_run_stages`
rows rather than assuming the caller "won't call it out of order" — the
whole point of ADR 0007 is that the guard is enforced server-side.

## 6. Report format

State explicitly, per protected table touched: whether any UPDATE/DELETE
was introduced, whether a mutable "current" flag was introduced, whether
grade corrections stay append-only, whether late-publication labeling is
correct, and whether every regenerate/publish/grade call path checks
`pipeline_run_stages` state before acting.
