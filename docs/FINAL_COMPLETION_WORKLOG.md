# Final Completion Worklog

Living document for the "CASSANDRA MLB STRIKEOUT ENGINE — FINAL
CORRECTNESS, LEARNING-SYSTEM, AND PRIVATE-BETA COMPLETION DIRECTIVE."
Updated as each phase completes. This session has repo/workspace access
only -- no Replit production access. Nothing in this document should be
read as a claim that anything is deployed or production-verified; see
each phase's "manual Replit actions" note for what Tyler must do.

## Starting state (Phase 0)

- Branch: `claude/repo-reset-jexzz6`
- Starting SHA: `1396fd969fc6631a7370d739679ba6b3fdcdf9fe` (matches the
  directive's "last independently reviewed commit" exactly -- confirmed
  via `git rev-parse HEAD`, no commits in between, no uncommitted changes
  at start).
- Full verification against a fresh scratch Postgres database
  (`cassandra_verify`, migrated via `alembic upgrade head`, dropped
  before/recreated for a clean run):
  - `alembic upgrade head`: applies cleanly through
    `b8975f126305` (add historical weather observations table).
  - `alembic check`: "No new upgrade operations detected."
  - `pytest`: **301 passed**, 0 failed, 1 pre-existing unrelated
    deprecation warning (`starlette.testclient` httpx usage).
  - `ruff check .`: all checks passed.
  - `mypy src`: no issues found in 82 source files.
  - Frontend (`web/`): `pnpm run typecheck` clean, `pnpm run lint` clean.

This matches the directive's claimed baseline (~301 tests) -- confirmed,
not assumed.

## Phase 1 audit -- confirmed findings (real code inspection, not assumed from the directive's text)

All six Phase 1 concerns were independently verified against the actual
HEAD code before any fix was written, per the directive's "verify before
modifying" rule. All six are **real, confirmed bugs**:

### 1A -- park-factor same-game/same-date leakage (CONFIRMED, CRITICAL)

`historical/dataset_builder.py`'s `build_training_dataset()`: the loop
over `targets` (ordered only by `HistoricalPitcherStart.game_date.asc()`,
a plain `date` column with no secondary tiebreaker) calls
`park_factor_accumulator.park_factor_for(venue)` to read a row's factor,
writes the row, then IMMEDIATELY calls
`park_factor_accumulator.record_outcome(venue, ...)` before moving to the
next row. Two starters from the *same game* (home + away, same venue,
same `game_date`) have no guaranteed relative ordering from a `date`-only
`ORDER BY` -- whichever one is processed second would see the first's
outcome already folded into its own park factor, since both share a
`game_date` and the accumulator has already been updated by the time the
second row reads it. This is a real point-in-time/self-referential
leakage bug, introduced in this same repository's most recent commit
(`1396fd9`, this session's own prior work). Confirmed by direct code
reading, not by running a failing test yet (a regression test is part of
the fix).

### 1B -- durable failed-run recording (CONFIRMED, CRITICAL for operability)

`orchestration/run_slate.py`'s `run_slate()`/`grade_slate_run()`: on
exception, the `except` block calls `_finish_run(status="failed")` and
adds a `RUN_FAILED` `AuditEvent`, then re-raises. Both callers
(`cli/main.py`'s commands, the scheduler, the API) run this inside
`db/session.py`'s `session_scope()`, which is confirmed (read directly)
to do `session.rollback()` on ANY exception before re-raising. Since
`run_slate()`'s `_start_run()`, every `_stage()` call, and the failure
marking are ALL on the same session/transaction with no intermediate
commit, a failure ANYWHERE in the pipeline (including late, e.g. mid-
PUBLISH) rolls back the ENTIRE transaction -- not just the failure
record, but the `PipelineRun` row itself and every previously-succeeded
stage row. **A failed run currently leaves zero trace in the database.**
Admin's status endpoint (which reads `PipelineRun`/`PipelineRunStage`)
would never show a failed run occurred at all. Confirmed by tracing the
actual transaction lifecycle, not assumed.

### 1C -- scheduler success-counting bug (CONFIRMED)

`orchestration/scheduler.py`'s `_run_slate_success_count_today()`:
counts `PipelineRunStage.stage == "PUBLISH", PipelineRunStage.status !=
"skipped"`. This counts `"running"` (a crashed/interrupted run stuck
mid-stage) and `"failed"` as "succeeded," not just `"succeeded"`.
Combined with 1B (a genuinely failed run currently leaves no row at all,
post-fix it WILL leave a `"failed"` PUBLISH row), this bug would
currently under-count in practice (nothing survives to be miscounted)
but would become a real bug the moment 1B is fixed, so both must land
together or in the correct order (1B first, so 1C's fix is verifiable
against real failed-run rows).

### 1D -- integer-line push probability (CONFIRMED)

`decision/engine.py`'s `decide()`: `probability_under = 1.0 -
probability_over`. For a half-integer line this is correct (no push is
possible). For an integer line, `probability_over = P(K > line)` is
correct, but `1 - probability_over = P(K <= line)` silently includes
`P(K == line)` (the push case) inside "under" -- there is no
`probability_push` field anywhere in `Decision`, the `projections` table,
or the API schema. A push is currently invisible and mis-attributed.

### 1E -- source-health counter pollution (CONFIRMED)

`ingestion/ingest_service.py`'s `_update_source_health()`:
`consecutive_failures` increments on ANY `success=False`, including the
expected/non-error `unavailable_reason` values `"pending"`, `"disabled"`,
`"quota_limited"`. `_source_health_status()` correctly labels these
states (`PENDING`/`DISABLED`/`QUOTA_LIMITED`, never `FAILED`) so the
*visible* status isn't currently wrong, but the underlying counter is
polluted -- a source that's legitimately `PENDING` for hours accumulates
a large `consecutive_failures` count that would cause a subsequent
*real* error streak to hit the `FAILED` threshold (3) almost immediately
instead of after 3 genuine consecutive errors, since the counter doesn't
distinguish expected-unavailable ticks from real failures.

### 1F -- missing-line synthetic-0.5 decision (CONFIRMED, CRITICAL for user trust)

`orchestration/run_slate.py`'s `run_slate()`: `decide_line = raw_line if
raw_line is not None else 0.5` -- when a confirmed starter has NO market
line at all, a synthetic `0.5` line is passed into `decide()` rather than
skipping/forcing `NO_PLAY`. Since `floor(0.5) == 0`, `probability_over =
P(K > 0)`, which is close to 1.0 for almost any real starting pitcher --
producing a large positive edge, very likely clearing
`DECISION_EDGE_THRESHOLD`, and landing as a fully `QUALIFIED` `OVER` pick
with **no reason code indicating the line was fake**. This directly
violates CLAUDE.md non-negotiable #4 ("No Play is a valid, expected
decision -- never force a pick") and Appendix A's `MARKET_CONTEXT_
INCOMPLETE` reason code, which exists in the vocabulary but isn't wired
to this path.

## Fix order

Prioritized by severity against CLAUDE.md's own non-negotiables (point-in-time
correctness and honest, never-forced decisions rank above operational
reliability, which ranks above cosmetic counter accuracy):

1. 1F (forced/fake pick from a missing line -- most user-facing risk)
2. 1D (push probability miscalculation -- direct grading/decision correctness)
3. 1A (park-factor self-leakage -- training-data integrity, not live-decision-facing but a real point-in-time violation)
4. 1B (durable failed-run recording -- required before 1C can be verified)
5. 1C (scheduler success miscounting -- depends on 1B)
6. 1E (source-health counter pollution)

Each gets its own focused commit with regression tests, per the
directive's rule #10. Progress recorded below as each lands.

## Phase 1 progress log

### 1F -- fixed

Re-verified before fixing: traced the actual call chain and found the
directive's most alarming claim ("could produce a QUALIFIED pick with a
fake line") does NOT fully materialize today --
`ingestion/quality_gate.py`'s `check_line_available()` already returns a
`fail`-severity `MARKET_CONTEXT_INCOMPLETE` finding when a pitcher has no
line, and `decide()`'s existing `fail_findings` gate already forces
`decision="NO_PLAY", decision_status="REJECTED"` before the edge/QUALIFIED
path is ever reached. The real, confirmed gap: `probability_over`/
`probability_under` were still computed from the caller's synthetic `0.5`
line and stored as if meaningful, even on a REJECTED row, and the
guarantee depended entirely on the caller (`run_slate.py`) remembering to
run the quality gate first -- not a structural property of `decide()`
itself.

Fix: `decision/engine.py`'s `decide()` now accepts `line: float | None`
directly and handles `None` as its own explicit branch -- returns
`NO_PLAY`/`REJECTED`, `probability_over=None`, `probability_under=None`,
adds `MARKET_CONTEXT_INCOMPLETE` to `reason_codes` if not already present
-- BEFORE any probability is computed from a line. `Decision.
probability_over`/`probability_under` changed from `float` to `float |
None` (the DB column, API schema, and frontend types/rendering were
already nullable/null-safe end-to-end -- confirmed by grep before
changing anything, so this closes a gap those other layers had already
anticipated). `run_slate.py` now passes `raw_line` straight through
instead of substituting `0.5`.

Tests: 4 new unit tests in `test_decision_engine.py` (forces REJECTED
even at an extreme mean, probabilities null, no reason-code duplication,
projection_mean/sd still visible for transparency). Extended the existing
`test_run_slate_then_grade_slate_end_to_end` integration test to assert
`probability_over`/`probability_under` are null and
`MARKET_CONTEXT_INCOMPLETE` is present for no-line entries (this test
already existed and passed before the fix, proving decision/
decision_status were already correct -- the new assertions are what
actually exercise the fix).

Verified: 305 tests passing (301 + 4 new) against a fresh scratch
database, ruff/mypy/guardrails clean.

Remaining limitation: none identified for this specific issue.

### 1D -- fixed

Confirmed real by tracing `decide()`'s math directly:
`probability_under = 1.0 - probability_over` is correct for a half-integer
line (no push possible) but silently folds `P(K == line)` into "under"
for an integer line. Cross-checked `grading/service.py`'s
`_grade_result()` -- the POST-GAME grading path already correctly handles
PUSH (comparing actual strikeouts to the line via `Decimal` equality,
independent of this bug) for both OVER and UNDER decisions -- so this fix
is purely about the PRE-GAME probability the model reports, not grading
correctness, which was already fine.

Fix: `decide()` now branches on `float(line).is_integer()`. Half-integer
line: `probability_push = 0.0` (unchanged behavior). Integer line:
`probability_push = cdf(line) - cdf(line - 1)` (P(K == line)),
`probability_under = cdf(line - 1)` (P(K < line), excluding the push).
`probability_over` unchanged either way (`1 - cdf(floor(line))`, correct
in both cases already). Added `Decision.probability_push: float | None`
(0.0 for half-integer, a real value for integer, `None` only when
`line is None`, consistent with 1F's null-probability contract) and
persisted it end-to-end: new `Numeric` column on `projections`
(migration `d71edca7eb30`), `ledger/service.py` passes it through,
`ProjectionOut` API schema + assembly, `web/src/lib/types.ts`, and
`ProjectionsTable.tsx` now shows a `P(push) X%` badge only when the value
is non-zero (so the common half-integer-line case is unaffected visually).

Scope decision, documented rather than silently skipped: the directive
also asked for a broader "market-policy layer" distinguishing sportsbook
lines-with-prices from manually-entered UnderDog-style lines with
possibly different push/refund behavior. Not built in this pass --
ADR 0006 already establishes that this system deliberately does NOT model
any specific vendor's payout/refund rules (Underdog's real payout math is
explicitly unresolved), and the existing edge/decision layer already only
ever compares against a neutral 0.5 baseline, never a vendor-specific EV.
Adding a new abstraction for a payout policy nobody has specified yet
would be inventing a product decision, which CLAUDE.md's rules explicitly
prohibit. The concrete, real math bug (push probability miscalculation)
is what's fixed here; the payout-policy question stays open for Tyler,
same as it already was for EV in general.

Tests: 7 new unit tests (`test_decision_engine.py`) covering push-
probability correctness, the three-way probability sum (over + under +
push == 1.0 for an integer line), the `line=0` edge case (no negative
`cdf()` call), and a fail-finding row still reporting real (not
zeroed-out) probabilities. 3 new frontend tests
(`ProjectionsTable.test.tsx`) for the push badge showing on an integer
line and staying hidden on a half-integer line.

Verified: 312 backend tests passing (305 + 7) against a fresh scratch
database, `alembic upgrade head` + `alembic check` clean, ruff/mypy/
guardrails clean; 26 frontend tests passing, typecheck/lint clean.

Remaining limitation: no vendor-specific payout/refund policy is modeled
(deliberately, see above) -- Tyler's decision, not guessed at.

### 1A -- fixed

Confirmed real by direct code tracing (see Phase 0 findings above) before
touching anything. Fix: `build_training_dataset()`'s main loop now groups
`targets` by `game_date` (via `itertools.groupby` -- `targets` is already
SQL-ordered by `game_date.asc()`, so this requires no extra sort). Every
row in a date's group reads `park_factor_accumulator.park_factor_for()`
against state frozen as of the END of the PRIOR date only; all of that
date's rows are written to the output file; only THEN are that whole
date's outcomes folded into the accumulator via `record_outcome()`, made
visible to a strictly LATER date. This means two rows sharing a
`game_date` -- including the opposing starter in the same game -- are
structurally guaranteed to see identical park-factor state, regardless of
whatever (arbitrary, DB-dependent) order the database happens to return
them in. Deliberately conservative: even two different games on the same
date that might have a real-world provable ordering are still treated as
mutually invisible, since this backfill has no reliable per-game
wall-clock "became Final" timestamp to justify anything finer-grained.

`DATASET_BUILDER_VERSION` bumped 0.2.0 -> 0.3.0 per the directive's
explicit instruction not to let the buggy and fixed behavior share a
version string. No dataset artifact was ever produced under 0.2.0 in this
repository or this sandbox (`data/training_datasets/` is gitignored and
none existed locally at the time of this fix), so there was nothing to
invalidate/rebuild/re-evaluate beyond the version bump itself.

Tests: 3 new integration tests (`test_dataset_builder.py`) -- two
starters in the same game get identical park factors, two different
games on the same date get identical park factors, and repeated builds
of the same seed data are deterministic. **Verification discipline
applied and it caught a real mistake in my own first test design**: my
first attempt at these tests seeded prior data at only ONE venue, which
passed even against the OLD BUGGY code -- because with a single venue,
`venue_rate` always trivially equals `league_rate` by construction
(exactly the pitfall `park_factors.py`'s own unit tests had already
taught earlier this session), so no leak could ever produce a numeric
skew large enough to fail the assertion. Caught by deliberately
`git stash`-ing the fix and re-running the new tests against the
pre-fix code before considering them done -- they passed, which should
never happen for a real regression test. Fixed by adding a second seeded
venue with a different baseline strikeout rate so `VENUE_ID`'s park
factor is a real, non-1.0 number a leak would visibly perturb; re-ran the
stash test again and confirmed the two leakage tests now fail cleanly
against the pre-fix code (`1.0526... != 0.9529...`) before restoring the
fix and confirming they pass.

Verified: 315 tests passing (312 + 3) against a fresh scratch database,
`alembic upgrade head`/`check` clean, ruff/mypy/guardrails clean.

Remaining limitation: the date-level batching is deliberately
conservative (see above) -- a future pass could compute real per-game
Final timestamps (if a reliable source existed) to allow same-date, later
games to see earlier same-date games' outcomes; not attempted here since
no such reliable timestamp source currently exists for this backfill.

### 1B -- fixed

Confirmed real by tracing the actual transaction lifecycle (see Phase 0
findings): `run_slate()`/`grade_slate_run()` marked a run failed and
added a `RUN_FAILED` audit event on the SAME `session` the caller's
`db/session.py` `session_scope()` rolls back on any exception -- so a
failed pipeline run left literally zero trace in the database (not even
the `PipelineRun` row `_start_run()` inserted survived), and Admin's
status endpoint could never show that anything had gone wrong.

Fix: a new `_record_failed_run()` writes the failure record via its OWN,
separately-committed session (`session_scope()` again, a fresh
connection), independent of the caller's doomed session. Which stages
genuinely completed before the failure is tracked in Python-level state
(`completed_stages`, appended by a small `_mark_succeeded()` wrapper
around the existing `_stage()` calls) rather than re-read from the
about-to-roll-back session, so the durable record is complete ("INGEST
and FREEZE genuinely succeeded, PROJECT failed") not just "something
failed somewhere." Added `_safe_error_detail()`, mirroring
`adapters/lines_odds_api.py`'s existing `_safe_fetch_error` pattern
(found during a live security review earlier in this build): never calls
`str(exc)` for `httpx.HTTPStatusError`/`httpx.RequestError`, since those
exception types embed the full request URL in their own `__str__`, which
for this codebase's real API-key-bearing adapter (the Odds API's `apiKey`
query parameter) would leak a live credential into the permanent,
undeletable `audit_events` table.

**A real, serious bug was found and fixed during this fix's own
verification, before any commit**: the first version of `_record_failed_run`
opened its fresh session and immediately tried to write a `PipelineRun`
row with the same `run_id` the caller's (still fully open, not-yet-
rolled-back) session had already inserted via `_start_run()`. Postgres
serializes concurrent inserts that could conflict on the same primary
key -- the fresh session's insert blocked indefinitely waiting for the
caller's transaction to resolve, which never happened, because that
transaction was itself waiting for `_record_failed_run()` to return. This
is a genuine deadlock, confirmed live (`pg_stat_activity` showed one
connection `idle in transaction`, another stuck on `INSERT waiting`) when
the first version of the new regression tests hung instead of failing --
this would have made ANY real pipeline failure hang the process
indefinitely in production, strictly worse than the original bug (which
at least failed cleanly, just silently). Fixed by having
`_record_failed_run()` call `session.rollback()` on the CALLER's session
first, releasing the lock, before opening the fresh session -- harmless
from the caller's perspective, since their own `session_scope()` would
roll back that same session again immediately after re-raising anyway.

A second real issue found while writing the regression tests' cleanup:
`audit_events` (and `projections`) have `DELETE` revoked at the database
grant level (CLAUDE.md non-negotiable #3) -- a test helper that tried to
delete a test-injected `AuditEvent` row failed with a real permission
error. This is correct, not a bug: a real failed run's audit trail is
exactly as permanent as a real successful run's. Test cleanup only
deletes `pipeline_runs`/`pipeline_run_stages` rows (genuinely mutable
operational tracking, confirmed via `db/models/pipeline.py`'s own
docstrings and the migration's `IMMUTABLE_TABLES` list) -- audit/
projection rows written by these tests remain permanently in whatever
database they ran against, same as a real failure would.

Tests: 5 new integration tests
(`test_run_slate_failure_recording.py`) injecting a real failure at each
of INGEST/FREEZE/PROJECT/PUBLISH (VALIDATE has no separate code path;
REVIEW is pure in-memory computation with nothing to fail against a real
backend) against the same real 2023-06-15 fixture slate
`test_run_slate.py` already uses -- confirming a durable failed
`PipelineRun`/`PipelineRunStage`/`AuditEvent` set survives even though
the calling session (the shared rollback-based `db_session` test
fixture) is never committed, that stages genuinely completed before the
failure are correctly recorded as `succeeded` (not lost), that no partial
`Projection` rows survive a mid-PUBLISH failure, and that an injected
`httpx.HTTPStatusError` with a fake secret embedded in its request URL
never appears in the stored failure detail.

`grade_slate_run()` received the same fix (its own `except` block calls
`_record_failed_run()` too) but no dedicated new test -- its only real
stage is GRADE, and the mechanism is identical to `run_slate()`'s,
already covered thoroughly there.

Verified: 320 tests passing (315 + 5) against a fresh scratch database,
`alembic upgrade head`/`check` clean, ruff/mypy/guardrails clean. No
stray Postgres connections/locks after the full suite (confirmed via
`pg_stat_activity`).

Remaining limitation: `run_slate()`'s own INGEST-through-PUBLISH business
data (raw ingestion rows, features, projections) for a failed run is
still atomically all-or-nothing (correctly rolled back) -- a run that
fails late (e.g. mid-PUBLISH) does not get to keep the real data an
earlier stage (e.g. INGEST) genuinely fetched from a live, quota-metered
vendor API; a retry re-fetches it. Not changed here (out of this fix's
scope -- the directive asks for durable FAILURE TRACKING, not durable
partial business data, and the two are structurally distinct in this
codebase, confirmed by the same audit that found this bug).

### 1C -- fixed

Confirmed real by tracing `orchestration/scheduler.py`'s
`_run_slate_success_count_today()`: the query filtered only on
`PipelineRunStage.stage == "PUBLISH"` and `PipelineRunStage.status !=
"skipped"`, which counts `"running"` (a crashed/interrupted run still
stuck mid-stage) and, since 1B, `"failed"` as if either were a completed
success. Before 1B this was unobservable -- a failed run left zero
`PipelineRunStage` rows at all, so there was nothing for this query to
miscount -- but now that a failed `run_slate()` genuinely leaves a
durable `PipelineRunStage(stage="PUBLISH", status="failed")` row (per
1B), undercounting it as a real success would make the scheduler believe
that hour's slot was already satisfied, silently suppressing the
legitimate retry for the rest of the day.

Fix: the query now requires BOTH `PipelineRun.status == "succeeded"` AND
`PipelineRunStage.status == "succeeded"` (in addition to the existing
`slate_date`/`stage == "PUBLISH"` filters) -- a run only counts as a real
success when the run-level status and the PUBLISH-stage status both
independently agree it completed.

Tests: 4 new integration tests added to the existing
`test_scheduler_reconciliation.py` (which already ran its 5 tests against
a real Postgres session, not mocks):
`test_zero_for_a_failed_publish_stage`,
`test_zero_for_a_still_running_publish_stage`,
`test_zero_when_publish_succeeded_but_the_run_itself_is_marked_failed`
(constructs a deliberately mismatched `PipelineRun.status="failed"` +
`PipelineRunStage.status="succeeded"` pair, proving the fix checks both
independently rather than either alone), and
`test_real_success_still_counted_alongside_a_failed_and_a_running_run`
(a realistic mixed-state date: one genuine success plus a failed retry
attempt and a still-in-flight run, proving the fix doesn't overcorrect
into undercounting real successes). Confirmed via `git stash` that all 4
new tests fail against the pre-fix query (`1 == 0` and `3 == 1` type
failures) before restoring the fix.

Verified: 324 tests passing (320 + 4) against a fresh scratch database,
`alembic upgrade head`/`check` clean, ruff/mypy/guardrails clean.

Remaining limitation: this fix corrects success *detection*, not
concurrency -- it does not by itself prevent two scheduler processes from
racing to start the same hour's run_slate() (that's Phase 2C's DB
advisory-lock item, not yet implemented). `run_slate()`/`grade_slate_run()`
being independently idempotent (per the module's own docstring) keeps a
race harmless today, but the advisory lock is still open work.

### 1E -- fixed

Confirmed real by tracing `ingestion/ingest_service.py`'s
`_update_source_health()`: `consecutive_failures` incremented on ANY
`success=False`, including the three EXPECTED/non-error
`unavailable_reason` values (`"pending"`, `"disabled"`,
`"quota_limited"`) alongside genuine errors. The visible status label
itself wasn't wrong (`_source_health_status()` already correctly labels
these `PENDING`/`DISABLED`/`QUOTA_LIMITED`, never `FAILED`, and
`api/routers/admin.py`'s `NEVER_BLOCKING_STATES` already excludes those
labels from `blocking_issues` regardless of the counter) -- but the
underlying counter itself was polluted. Traced the concrete failure
scenario this causes: a source that's legitimately `PENDING` for many
ticks (e.g. a line that hasn't posted yet) silently accumulates a large
`consecutive_failures` count; the moment a genuine error occurs
afterward (`unavailable_reason` unset/`"error"`),
`_source_health_status()` falls through to the real-failure branch and
reads the now-inflated counter, so the FIRST real error after a long
pending streak immediately reports `FAILED` (and becomes a live
`blocking_issues` entry -- `FAILED` is not in `NEVER_BLOCKING_STATES`)
instead of `DEGRADED`, misrepresenting a single fresh error as an
already-persistent 3-in-a-row failure streak.

Fix: `_update_source_health()` now only increments `consecutive_failures`
for a genuine failure (`unavailable_reason` not in
`{"pending", "disabled", "quota_limited"}`) -- an expected-unavailable
tick leaves the counter untouched (neither incremented nor reset), so a
real error streak starting after a long expected-unavailable period is
correctly read as starting fresh. `last_failure_at`/`last_status` still
update on every non-success tick as before (visibility into the last
non-success tick is unaffected); only the failure-streak counter's
semantics changed.

Tests: 5 new/updated tests in `test_ingest_service.py`. Updated the
existing `test_ingest_unavailable_source_still_writes_audit_and_health`
(UmpireStubAdapter, `unavailable_reason="disabled"`), whose assertion had
encoded the bug itself (`consecutive_failures == 1` for a permanent
by-design stub) -- now asserts `== 0`. Added
`test_pending_ticks_never_accumulate_consecutive_failures`,
`test_quota_limited_ticks_never_accumulate_consecutive_failures`,
`test_real_errors_still_accumulate_consecutive_failures` (proving the fix
doesn't stop counting genuine errors), and
`test_a_real_error_after_a_long_pending_streak_starts_a_fresh_streak_not_failed`
(the exact scenario the audit described -- 10 PENDING ticks then 1 real
error must read `consecutive_failures == 1`/`DEGRADED`, not `FAILED`),
plus `test_success_still_resets_consecutive_failures_to_zero`. New tests
call `_update_source_health()` directly (same pattern as 1C's direct
`_run_slate_success_count_today()` tests) since it's the exact unit under
audit. Confirmed via `git stash` that 4 of the 5 new/changed assertions
fail against the pre-fix code (`5 == 0`, `11 == 1`, etc.); the 5th
(genuine-error counting) correctly still passes pre-fix, since that
behavior was never broken.

Verified: 329 tests passing (324 + 5) against a fresh scratch database,
ruff/mypy/guardrails clean.

Remaining limitation: none identified -- this was a narrowly-scoped
counter-semantics fix with no schema change and no behavior change for
the genuine-failure path.

**All six Phase 1 items (1A-1F) are now complete.** Phase 2 (Replit
runtime reliability, repo-prep only -- no deploy access, see the top of
this document) begins below.

## Phase 2 -- Replit runtime reliability

### 2B -- deployed git commit SHA visibility (fixed)

Confirmed real: `GET /health` returned a bare `{"status": "ok"}` with no
build/version identity at all, and `AdminStatusResponse` (the Admin
page's data source) exposed `model_version`/`decision_policy_version`/
`feature_set_version` but no git commit SHA -- an operator had no way to
confirm which actual commit was running on a given deployment, even
though `config.py`'s `get_git_commit_sha()` (prefers an explicit
`GIT_COMMIT_SHA` env var set at deploy time, falls back to `git
rev-parse HEAD` for local/dev, returns `None` rather than raising) has
existed since Phase 8/ADR 0010 and was already wired into every
`Projection` row's own `git_commit_sha` field -- just never surfaced at
the deployment level.

Fix: `GET /health` now returns `{"status": "ok", "git_commit_sha": ...}`.
`AdminStatusResponse` gained a `git_commit_sha: str | None` field
(`api/schemas.py`, `api/routers/admin.py`), surfaced on the Admin page
next to the existing model/policy/feature-set version line
(`web/src/app/admin/page.tsx`, `web/src/lib/types.ts`). Per the
directive's explicit requirement ("missing SHA must be a visible
warning, not silent"), a `None` SHA is appended to
`AdminStatusResponse.blocking_issues` with a message naming the fix
(`GIT_COMMIT_SHA` env var) -- there is no separate "warnings" channel in
this schema today, so `blocking_issues` is the only existing
operator-visible surface; reusing it was a deliberate choice over adding
a new response field for a single warning message.

Did NOT attempt to make `/health` distinguish
engine-initializing/engine-ready/engine-failed (part of 2A, tracked
separately below) -- documented directly in `main.py`'s `health()`
docstring why that specific distinction isn't observable from inside
this handler at all (it only ever runs once the process is already
listening, which is always after migrations/lifespan-gate have already
resolved one way or the other), and why building that visibility would
require a change on the Next.js side (the only publicly exposed port on
Replit), which ADR 0012 requires the owner to sign off on before adding
any new frontend surface -- not silently invented here.

Tests: 3 new (`test_health.py`: default `status: ok`, a monkeypatched
real SHA round-trips through `/health`, a monkeypatched `None` SHA
returns `200` with `git_commit_sha: null` rather than erroring) + 2 new
in `test_admin_router.py` (`test_admin_status_with_correct_secret_...`
extended to assert the SHA round-trips and isn't itself a blocking
issue; new `test_admin_status_warns_when_git_commit_sha_is_unavailable`
asserting the `None` case produces both `git_commit_sha: null` and a
matching `blocking_issues` entry).

Verified: 333 tests passing (329 + 4 backend -- one test file gained 2
tests, one gained 1, plus the new file's 3, net +4 after accounting for
the extended existing test) against a fresh scratch database,
ruff/mypy/guardrails clean; frontend `tsc --noEmit`, `eslint`, and
`vitest run` (26 tests) all clean.

(Mid-verification note, unrelated to this change: the shared dev
Postgres cluster had stopped between sessions -- `service postgresql
start` before re-running the suite; not a regression from this commit.)

Remaining limitation: `git_commit_sha` is only as trustworthy as whoever
sets `GIT_COMMIT_SHA` at Replit deploy time -- this repo cannot verify
Tyler actually sets it correctly on a real deployment (no deploy
access); README/DEVELOPMENT docs should say to set it from the actual
deployed commit, covered under 2D's documentation pass below if not
already present.

### 2A -- engine startup supervision (fixed, NOT production-verified)

Confirmed real by tracing `scripts/replit_start.sh`'s deployment-mode
block: the engine (dependency install, migrations, `uvicorn`) ran as a
single background subshell (`ENGINE_PID`), while Next.js ran in the
*foreground* as the last statement of the script. Because `set -e` does
not apply to a background job's failure, if the engine subshell died for
any reason -- a migration error, an uncaught startup exception, `uvicorn`
crashing -- the main script had no way to notice: it just kept running
the foreground `pnpm run start` indefinitely. The `trap ... EXIT` only
fires when the *whole script* exits, so it never caught this case either.
Net effect: a completely dead engine could leave Next.js serving on port
3000, satisfying Replit's port-based healthcheck and looking "healthy"
forever, while every page's server-side fetch to the engine silently
failed from that point on -- exactly the "misleadingly healthy frontend"
failure mode the directive calls out.

Fix: the frontend (`pnpm run start`) is now also started as a background
job (`WEB_PID`), and the script blocks on `wait -n` (waits for whichever
of the two background jobs finishes first -- no PID arguments needed
since there are only ever these two, so this form works back to bash
4.3, not just versions supporting `wait -n PID`). Whichever job exits
first is the failure signal (neither is expected to ever exit on its own
during a healthy deployment); the script identifies which one via
`kill -0 "$ENGINE_PID"`, logs which process died and with what exit code,
kills the other via the (extended) `trap`, and exits with that same
non-zero code -- so Replit sees the whole script/process exit non-zero
rather than a partially-alive deployment.

Also: removed a duplicate "starting engine API" log line left over from
editing (the phase-transition log now fires exactly once, immediately
before the actual `uvicorn` invocation, right after the "migrations
complete" moment) and updated the file's own top-of-file summary comment
to describe the new supervised-background-jobs behavior instead of the
old foreground-frontend description.

Verification: no Python/frontend code changed, so `pytest`/`mypy`/
`vitest` are unaffected (guardrails re-run clean, 126 files checked --
one more than 2B's 125 since this touches a new file type it now walks).
`bash -n scripts/replit_start.sh` (syntax check) passes. The core
`wait -n`/`kill -0` logic was exercised standalone in two throwaway
sandbox scripts simulating each failure order (engine dies first;
frontend dies first) -- both correctly identified the dead process,
killed the survivor via the trap, and exited with the dying process's
real exit code (verified `7` and `3` respectively propagate through).

**This fix is explicitly NOT verified against a real Replit deployment**
(no deploy access this session, per this document's and CLAUDE.md's own
repeated constraint) -- `CURRENT_STATE_AUDIT.md`'s "Not verified against
real infrastructure this session" section now carries the same caveat.
Two real unknowns that only a live redeploy can answer: whether Replit's
actual bash version behaves identically for bare `wait -n`, and whether
Replit's deployment platform actually treats a non-zero script exit as
"unhealthy"/restart-eligible the way this fix assumes (vs., say, just
leaving the container stopped with no visible alert). Tyler should
redeploy with this change and deliberately break something (e.g.
temporarily point `DATABASE_URL` at an unreachable host) to confirm the
whole deployment visibly goes down rather than partially surviving.

Remaining limitation: dev/workspace mode (the `else` branch) was left
unchanged -- the frontend still runs in the foreground there, and an
engine crash only shows up as an interleaved log line in the same
terminal Tyler is already watching interactively, which is a reasonable,
lower-stakes failure mode for an interactive session (killing the whole
dev server the moment the engine crashes once, mid-iteration, would be
more disruptive than helpful for local development). Not applying the
same supervision there was a deliberate scope choice, not an oversight.

### 2C -- scheduler reliability: configurable cadence + duplicate-process advisory lock (fixed)

Confirmed real by re-reading `orchestration/scheduler.py` against the
directive's specific asks: `POLL_INTERVAL_SECONDS`/`GRADE_LOOKBACK_DAYS`
were hardcoded module constants (unlike `auto_run_hours_local`/
`operating_timezone`, already `settings`-backed) -- retuning cadence
needed a code change, not a config change. There was also no defense at
all against two scheduler *processes* running against the same database
concurrently -- `run_slate()`/`grade_slate_run()` being independently
idempotent makes this data-safe today, but a second process would still
silently double-spend metered vendor API quota (Odds API, MLB Stats API)
for zero benefit. Confirmed overlapping ticks within a single process
were already structurally impossible -- `_scheduler_loop` is one thread
that blocks on `run_scheduled_tasks()` before its next `wait()`, so no
separate per-task lock was needed for that specific directive item; this
finding is documented in the module's own top docstring rather than
adding redundant locking machinery for a race that can't occur.

Fix, two parts:
1. `config.py` gained `scheduler_poll_interval_seconds` (default `900`,
   matching the old constant) and `scheduler_grade_lookback_days`
   (default `3`, same) as real `Settings` fields, same style as the
   existing `auto_run_hours_local`. `scheduler.py` now reads both from
   `settings` instead of module constants.
2. New `_run_scheduled_tasks_locked()` wraps `run_scheduled_tasks()` in a
   non-blocking Postgres session-level advisory lock
   (`pg_try_advisory_lock`/`pg_advisory_unlock` on a fixed arbitrary key)
   acquired via a raw `engine.connect()` (not `session_scope()`, since
   the lock must span `run_scheduled_tasks()`'s own several independent
   transactions, then be explicitly released rather than
   auto-releasing with any one of them). If another process already
   holds the lock, this instance logs a WARNING and skips the entire
   tick rather than blocking. `_scheduler_loop` now calls this wrapper
   instead of `run_scheduled_tasks()` directly.

Tests: 2 new unit tests in `test_scheduler.py`
(`test_run_scheduled_tasks_respects_configured_grade_lookback_days`,
`test_scheduler_loop_uses_the_locked_wrapper_and_configured_poll_interval`
-- the latter via a small `_RecordingStopEvent` test double, confirming
`_scheduler_loop` calls the new locked wrapper, not the old direct call,
and passes through the configured poll interval) + 4 new integration
tests in a new `test_scheduler_advisory_lock.py` against a real Postgres
connection (advisory locks are a genuine server-side primitive a mock
session can't exercise): runs normally when the lock is free; skips
(never calling `run_scheduled_tasks`) when a second real connection
already holds the lock; releases the lock so a later call can reacquire
it; releases the lock even when the wrapped call raises (proven by a
fresh probe connection successfully re-acquiring the lock afterward, not
by inspecting internal state). Confirmed via `git stash` that all 6 new
tests fail against the pre-fix code (`AttributeError` on the not-yet-
existing function/settings fields, since this is new capability rather
than a behavior-preserving bug fix -- the meaningful proof here is that
the failure is exactly "this code doesn't exist yet," not a vacuous
assertion).

Verified: 339 tests passing (333 + 6) against a fresh scratch database,
ruff/mypy/guardrails clean.

Remaining limitation: same as the rest of Phase 2 -- the advisory lock's
actual behavior under two real concurrent Replit processes has not been
(and cannot be, from this session) verified against live infrastructure;
only the SQL primitive itself and the wrapper's control flow were
exercised, both against a real local Postgres. This is defense-in-depth
for a scenario the current single-instance deployment shouldn't create
in the first place, not a fix for an observed production incident.

### 2D -- database migration verification + backup documentation (fixed)

Confirmed real by checking what actually existed: every migration under
`db/migrations/versions/` already has a real `downgrade()` (not an
autogenerated `pass` stub) -- traced each of the 8 files individually
(see this entry's own verification run below) -- but the full downgrade
chain had never actually been exercised end-to-end in this session's own
record, and neither `README.md` nor `docs/DEVELOPMENT.md` said anything
about backing up the database before a deploy that runs a migration, even
though `scripts/replit_start.sh` always runs `alembic upgrade head`
automatically on startup with no manual confirmation step.

Verification performed (not a code change, a real test run): from a
freshly migrated scratch database, `alembic downgrade base` walked the
entire chain backward cleanly (`d71edca7eb30` all the way to the
unversioned base, all 8 migrations, no errors), then `alembic upgrade
head` walked it forward again cleanly, then `alembic check` reported "No
new upgrade operations detected" (model metadata matches the schema
exactly, no drift). This is the fresh-DB + upgrade-from-head + downgrade
+ `alembic check` combination the directive asked for, run against the
real current migration chain rather than assumed from reading the files.

Fix (documentation, since the actual migration/downgrade coverage was
already sound): added a "Before redeploying a live instance: back up the
database" section to `README.md`'s Replit deployment guide -- concrete
Neon/Supabase backup instructions plus a portable `pg_dump`/`pg_restore`
fallback, and an explicit statement that `alembic downgrade` is schema-
only and never a substitute for a real backup (lossy downgrades exist,
e.g. a dropped column's data is gone regardless of the migration file's
own correctness). Also added a migration-verification checklist to
`docs/DEVELOPMENT.md`'s Database section (the same 4-step
upgrade/check/downgrade/grant-review process used to verify this entry,
now written down so the next migration -- human or Claude-authored --
follows the same discipline instead of re-deriving it). README's Replit
Secrets list also gained `GIT_COMMIT_SHA` (closing 2B's own documented
follow-up) and `SCHEDULER_POLL_INTERVAL_SECONDS`/
`SCHEDULER_GRADE_LOOKBACK_DAYS` (2C's new settings) as optional
overrides, so both are discoverable from the deployment doc, not just
`.env.example`.

Tests: none (documentation + a verification run, no code changed).
`scripts/guardrails.py` re-run clean (127 files -- one more than 2C's
126, the new checklist prose in `DEVELOPMENT.md` doesn't add a file but
`README.md`'s edit does get walked; file count moves with whatever the
guardrail script's own file-discovery picks up across doc edits).

**This closes all of Phase 2's directive items (2A/2B/2C/2D).** As with
2A/2C, the backup *instructions* themselves are standard, well-known
provider features (Neon branching, Supabase's backup page, `pg_dump`)
documented here for Tyler's convenience, but actually exercising a real
backup/restore cycle against a live Neon/Supabase instance is something
only Tyler can do (no deploy/production database access this session).

## Phase 3 -- model artifact + registry system

### 3A/3B/3C -- durable model artifacts, model registry, `train-final-model` CLI (implemented)

Confirmed the starting state by tracing `historical/challenger_poisson.py`
and `historical/walk_forward.py`: the existing Poisson-regression
challenger only ever exists as an in-memory `PoissonRegressionModel`
produced fresh by each walk-forward fold's fit -- nothing durable is ever
written except each comparison run's own frozen `HISTORICAL_RECONSTRUCTION`
evaluation report. There is no artifact storage, no versioned coefficient
record, and no registry of any kind, matching `CURRENT_STATE_AUDIT.md`'s
own prior "Not yet built... a model registry" note.

**3A -- durable model artifacts.** New `model_artifacts` table
(`db/models/registry.py`, migration `e076e6061a06`) carries every field
the directive named: unique `artifact_id`/`fitted_model_version`,
`model_family`/`model_code_version`, `coefficients` + `coefficient_order`
(JSONB, self-describing -- a stored artifact never needs its fitting
code's source to interpret it) + a redundant `intercept` column,
`preprocessing_rules` (defaults/clipping/regularization actually in
effect for that fit), full training-dataset provenance
(`training_dataset_id`, `dataset_builder_version`,
`availability_policy_version`, `feature_set_version`, `training_seasons`,
`training_game_types`, `training_row_count`, `trained_at`),
`source_git_sha` (`config.get_git_commit_sha()`, already built for 2B),
`artifact_checksum` (a sha256 reproducibility hash over exactly the
fields that determine predictions, ADR 0010's spirit applied to a model
instead of a projection), `dependency_versions`, `training_metrics`,
`evaluation_report_ids` (pointers into `historical/evaluation.py`'s own
frozen report files, not a copy), `notes`, and `created_by`. Append-only
at the database grant level: applied the FULL correct pattern (`REVOKE
UPDATE, DELETE, TRUNCATE` + re-`GRANT UPDATE` + a `BEFORE UPDATE OR
DELETE` trigger reusing the existing `cassandra_block_immutable_mutation`
function) in one migration, rather than replaying the three-migration
mistake-then-fix history `raw_*`/`projections` originally needed --
that history's *lessons* (a bare `REVOKE UPDATE` breaks any FK-referenced
table's inbound inserts; `TRUNCATE` needs its own separate `REVOKE`) were
already known going in. Verified empirically against the scratch
database, not just read from the migration file: a real `INSERT`
succeeds, a real `UPDATE`/`DELETE`/`TRUNCATE` against `model_artifacts`
each fail (trigger exception / permission denied), and a real `INSERT`
into `model_registry_events` (which FK-references `model_artifacts`)
succeeds -- proving the FK row-lock case the original `d764bb3bb5c1` fix
exists for is actually exercised, not just theoretically covered.

**3B -- model registry.** New `model_registry_events` table, also
append-only. `MODEL_REGISTRY_STATES` defines the full directive
vocabulary (`CANDIDATE`/`SHADOW`/`APPROVED`/`ACTIVE`/`RETIRED`/
`REJECTED`/`ROLLED_BACK`) as a DB `CHECK` constraint. Deliberately **no
mutable status column anywhere** -- CLAUDE.md non-negotiable #3 already
forbids exactly this pattern (the same reasoning behind `projections`
never getting an `is_current` flag), so an artifact's "current status"
is always `registry/service.py`'s `current_status()` querying the latest
event, not a stored flag. `registry/service.py` provides the general
primitives (`create_model_artifact`, `record_registry_event`,
`compute_artifact_checksum`, `current_status`) plus one specific
transition, `register_as_candidate()` (event_type="registered",
from_status=None, to_status="CANDIDATE") -- the only one any code in
this build actually calls. `record_registry_event()` is written
generically enough for a future promote/shadow/rollback CLI action to
call, but nothing wires it to anything else today; this is an honest,
documented scope boundary (the mission directive's own text was
truncated mid-example right after describing 3C, so no further phases'
requirements were ever provided) -- not silently invented, not silently
omitted either, per CLAUDE.md non-negotiable #7.

**3C -- `cassandra train-final-model` CLI.** `--dataset-id ds_... --family
poisson-regression --operator <name> [--register] [--notes ...]`
(`cli/main.py`, orchestration in `historical/train_final_model.py`).
Loads one frozen dataset (reusing the exact same manifest/row-loading
`train-walk-forward-challenger` already uses), fits a FINAL challenger
on every eligible row (no walk-forward holdout -- a genuinely different
tool than `train-walk-forward-challenger`, which answers "is this model
family competitive" via held-out folds; this answers "freeze the actual
artifact a human might promote"), evaluates it (necessarily in-sample,
since a final fit has no held-out data by construction -- documented
explicitly, not hidden), writes the durable artifact, and -- only with
`--register` -- registers it as `CANDIDATE`. **Validates artifact
serialization/reload for real**: after the artifact-creating transaction
commits, a genuinely separate `session_scope()` re-queries the row
(proving an actual JSONB round-trip, not a cached ORM object),
reconstructs a `PoissonRegressionModel` from the reloaded coefficients,
and the function raises `RuntimeError` if either the raw coefficients or
a full re-run of `evaluate_model()` against the reloaded model don't
match the original fit exactly. `train_final_poisson_model()`
deliberately manages its own multiple `session_scope()` calls rather
than taking a caller-supplied session (every other orchestration
function in this codebase takes one) -- the reload step is meaningless
unless the artifact write has actually committed first; same reasoning
Phase 1B's `_record_failed_run` needed its own separate session for.
**Never auto-promotes**: `CANDIDATE` is structurally the only status
this command (or any code in this build) can reach.

Also: renamed `challenger_poisson.py`'s private `_DEFAULT_REST_DAYS` to
public `DEFAULT_REST_DAYS` and added a new public `COEFFICIENT_NAMES`
tuple (naming `_design_row()`'s positions in order) so an artifact's
`coefficient_order` is generated from the same source of truth the
design row itself uses, rather than a hand-typed parallel list that
could drift; `train_final_poisson_model()` raises if the two ever get
out of sync in length. Added `model_artifacts`/`model_registry_events`
to `scripts/guardrails.py`'s `IMMUTABLE_TABLES`/
`IMMUTABLE_MODEL_CLASS_NAMES` so the same pre-commit hook that protects
`raw_*`/`projections`/`grades`/`audit_events` from an accidental
UPDATE/DELETE-shaped edit now also protects these two new tables.

Tests: 12 new integration tests in `test_registry_service.py` (using the
rolled-back `db_session` fixture, so nothing here permanently pollutes
the shared database) covering artifact field population, checksum
determinism/sensitivity, the `coefficient_order[0] == "intercept"`
guard, real UPDATE/DELETE trigger-blocking against both new tables,
`register_as_candidate`'s event shape, `current_status()` before and
after registration, and `record_registry_event`'s invalid-status guard.
6 new integration tests in `test_train_final_model.py` (against the real
database -- `train_final_poisson_model()` manages its own committed
sessions, so unlike the registry-service tests these do leave permanent
rows, matching the accepted 1B precedent; each test uses a unique
synthetic `dataset_id`) covering unregistered-by-default creation,
registration-on-request, the reload/re-evaluation round-trip (both via
the function's own internal validation succeeding without raising, and
independently re-querying the artifact afterward), the evaluation report
file actually being written, and finite/non-negative training metrics.

Verified: 357 tests passing (339 + 18) against a completely fresh
scratch database (dropped and recreated, not just reused), `alembic
upgrade head`/`check` clean from empty, ruff/mypy/guardrails clean
(guardrails run both against the full tracked tree and explicitly
against just the staged Phase 3 files, confirming the new
`session.add()`/`session.flush()` calls in `registry/service.py` don't
false-positive the mutation-block check).

Remaining limitations, all deliberate scope boundaries rather than
oversights: (1) only `poisson-regression` is a supported `--family`
today -- `SUPPORTED_MODEL_FAMILIES` exists as a real extension point, but
no second family is implemented (matches the pre-existing "not yet
built: negative-binomial/gradient-boosted challenger" gap `CURRENT_STATE_
AUDIT.md` already documented). (2) No promotion/shadow/rollback CLI
action exists -- the registry schema and `record_registry_event()`
support the full state vocabulary, but reaching any status past
`CANDIDATE` requires code that doesn't exist yet. (3) The registry is
not wired into the live decision engine/`run_slate()` at all --
`models/baseline.py`'s permanent, unmodified baseline is still the only
model either one ever calls, exactly as before this phase; ADR 0003's
`StrikeoutModel` interface already makes a future swap mechanical, but
building that swap (plus the "exactly one ACTIVE model, permanent
baseline as guaranteed fallback" logic the directive describes) is real
future work this session's truncated directive text never actually
specified the shape of.

## Post-Phase-3 -- real Replit deployment verification (Tyler, 2026-08-07)

This session has no Replit deployment access at all (repeated constraint
throughout this document). Tyler redeployed `cassandrahits.replit.app`
himself at commit `144fd1e148678fafe0d8042b065247b3e7bc06c9` (HEAD of
`claude/repo-reset-jexzz6` after Phase 3) and reported the results back
into this session verbatim. Recorded here as real evidence, distinct
from anything this session could itself verify:

- Took a real pre-deploy backup (`cassandra-backup-20260807T054741.dump`,
  4.8 MB) before pulling -- the exact discipline 2D's new README section
  asks for.
- `alembic upgrade head` applied `d71edca7eb30 -> e076e6061a06` (Phase
  3's model-artifacts/registry migration) against the real production
  database; `alembic check` reported no drift.
- Set `GIT_COMMIT_SHA` as a real Secret for the first time (2B's new
  requirement) and confirmed `http://127.0.0.1:8000/health` (loopback,
  from inside the Repl) returns it exactly.
- `curl -sI https://cassandrahits.replit.app/` returns real HTML
  (`content-type: text/html`, `x-powered-by: Next.js`), not the engine's
  JSON 404 -- **this closes out the one previously-"not yet confirmed"
  item from the prior deployment session** (the port-routing bug
  documented above under "Verified against real infrastructure"; see
  that entry, now updated).
- `/api/today` returns valid JSON (`projection_count: 0` -- correct and
  expected, since no `run_slate()` had fired yet for that slate date).
- Deployment logs show the exact intended startup order: migrations ->
  engine ready -> frontend ready.

**Still not verified even after this**: 2A's actual failure-teardown
behavior. This redeploy only exercised the successful startup path --
nobody deliberately broke the engine (e.g. an unreachable
`DATABASE_URL`) to confirm the whole deployment visibly goes down rather
than the frontend surviving alone. `CURRENT_STATE_AUDIT.md`'s own 2A
entry is updated to reflect this exact partial state, not overclaimed as
fully verified.

## Phase 4 -- closing the self-learning loop (Tyler's explicit request:
"build what it needs... to make the best and most accurate projections &
so we can get the self learning loop ball rolling")

Phase 3 built artifact storage and a registry that could represent
CANDIDATE, but nothing could ever reach ACTIVE and the live pipeline
never looked at the registry at all -- training a challenger was a dead
end. This phase wires it up: a promoted model actually serves live
predictions, with a human-gated promotion/rollback action and the
permanent baseline as a guaranteed fallback.

### 4.1 -- numpy-free model split (prerequisite, done)

Confirmed a real architectural conflict before writing anything else:
`historical/challenger_poisson.py`'s `PoissonRegressionModel.predict()`
used `np.array`/`np.dot` for what is just a length-5 dot product, and the
whole module does a top-level `import numpy as np` -- so reconstructing
and serving a fitted artifact from the live pipeline would have silently
made `numpy` a hard live-deployment dependency, contradicting this
project's own established boundary ("kept out of the live pipeline's
core dependencies," stated in `challenger_poisson.py`'s original
docstring and `CURRENT_STATE_AUDIT.md`).

Fix: split the model class out into a new `models/poisson_regression.py`
-- numpy-free (`design_row()`'s dot product is a plain Python `sum()`
now), safe to import from anywhere, including the live pipeline.
`historical/challenger_poisson.py` keeps only the genuinely numpy-
dependent IRLS fit (`fit_poisson_regression`) and re-exports everything
from the new module, so every existing `from
cassandra.historical.challenger_poisson import ...` call site
(`walk_forward.py`, `train_final_model.py`, existing tests) is
byte-for-byte unaffected -- zero call sites needed to change.

Tests: 7 new in `tests/unit/test_poisson_regression.py` -- `design_row()`
shape/defaults, three hand-computed `predict()` values (not just re-
deriving the formula under test), the eta-clipping behavior, CDF
validity, and (the actual point of this split) a subprocess test that
imports only `cassandra.models.poisson_regression` in a fresh Python
process and asserts `numpy` never enters `sys.modules` -- proving the
live-safe boundary for real rather than by inspection.

Verified: 364 tests passing (357 + 7) against the scratch database,
ruff/mypy/guardrails clean.
