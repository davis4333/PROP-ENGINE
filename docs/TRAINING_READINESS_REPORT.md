# Training Readiness Report

**Status as of this pass: not ready to train. No model has been trained
or evaluated.** This is a direct, honest statement, not a placeholder —
see below for exactly what's blocking it and what's already done.

## What exists

- A resumable, idempotent historical backfill (`historical/backfill.py`)
  actually collecting real 2023-present MLB schedule/game, actual-starter,
  pitcher-outcome, and lineup data — running at the time this report was
  written (see `HISTORICAL_COVERAGE_REPORT.md` for the point-in-time
  snapshot, and the final session report for the exact stopping point).
- A designed (not implemented) availability policy
  (`HISTORICAL_AVAILABILITY_POLICY.md`) specifying how a
  `STRICT_LIVE_COMPATIBLE` training tier must be constructed without
  leakage.
- A designed (not implemented) training dataset spec
  (`TRAINING_DATASET_SPEC.md`).
- The permanent baseline model (`k-model-0.1.0`,
  `models/baseline.py`) already exists and runs live — but it has never
  been evaluated against historical outcomes at scale, only against live
  slates as they occur.

## What's blocking training

1. **The training-dataset builder doesn't exist.** `historical_pitcher_
   starts` has real outcome data, but nothing yet joins it with
   availability-filtered pregame features per the policy doc and freezes
   a versioned dataset. Building this is real engineering work, not a
   trivial follow-up.
2. **Several pregame feature domains this backfill was scoped to collect
   aren't collected yet**: park factors calculated from prior games,
   historical weather, opponent rolling strikeout context, pitch-level
   detail (see `HISTORICAL_BACKFILL_DESIGN.md`'s "out of scope" list).
   A first model comparison could reasonably proceed with a reduced
   feature set (recent K-rate, batters faced, rest days, handedness,
   identity) and report performance with-and-without the missing groups,
   per the mission directive's own evaluation requirements — but that
   still needs the dataset builder first.
3. **The backfill itself was still running when this session ended** —
   see the final report for exact coverage at the stopping point. A
   dataset built from partial coverage would need to honestly label
   which seasons/domains it actually drew from.

## What happens next (not done in this pass)

Once the backfill completes (or reaches sufficient coverage) and the
dataset builder exists:

1. Build `STRICT_LIVE_COMPATIBLE` (default) and optionally
   `RETROSPECTIVE_ENRICHED` datasets, run the required leakage checks
   (see the test-requirements list in the mission directive: same-game
   outcome leakage, future-season aggregate leakage, lineup/weather
   availability leakage), freeze and version the result.
2. Evaluate the permanent baseline (`k-model-0.1.0`) against it —
   MAE, RMSE, mean bias, Poisson deviance, calibration at common
   half-lines, Brier score, broken out by season/handedness/projected-K
   range/sample-size tier, with and without optional feature groups.
3. Train at least one challenger count model (Poisson regression,
   negative-binomial, or a gradient-boosted count model) using
   time-ordered walk-forward validation — train on earlier dates,
   validate on later dates, roll forward, never train on games after the
   evaluation game.
4. Produce a comparison report and recommendation. **No automatic
   promotion** — production promotion requires explicit human approval,
   per the mission directive.
5. Historical market-line hit rate stays labeled "unavailable" unless
   genuine historical lines are imported separately (out of scope for
   this phase per the mission directive itself — a count model trains on
   actual strikeout outcomes, not market lines).

## Explicit statement

No historical model evaluation, backtest, or walk-forward result exists
anywhere in this repository as of this pass. Nothing has been written to
the live `projections`/`grades` tables by anything other than the live
pipeline. This report exists specifically so that fact is unambiguous and
checkable, not implied by silence.
