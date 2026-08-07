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
