# Training Readiness Report

**Status as of this pass: the 2023-present backfill has completed (0
failures), and a full walk-forward comparison exists across all three
complete regular seasons.** A real, leakage-tested training dataset can
be built; the permanent baseline (`k-model-0.1.0`, unchanged) and a
Poisson-regression challenger can both be evaluated against it under
time-ordered walk-forward validation. **The challenger beat the baseline
on every one of 7 folds spanning 2023-2025** (numbers below) — the
strongest and most complete challenger-vs-baseline result this project
has produced. This is a direct, honest statement, not a placeholder —
see below for exactly what's done, what's still not built, and the
caveats on that result.

## What exists

- A resumable, idempotent historical backfill (`historical/backfill.py`)
  actually collecting real 2023-present MLB schedule/game, actual-starter,
  pitcher-outcome, and lineup data — see `HISTORICAL_COVERAGE_REPORT.md`
  / `audit-historical-coverage` for the current point-in-time coverage.
  **2023-2025 regular seasons are complete** (0 failed games across the
  whole 2023-01-01-to-present range); 2026 is complete through the
  season's current point-in-time (in progress, real games still being
  played). A small number of games remain `skipped` (not yet `Final` --
  postponed/rescheduled or genuinely in-progress at the time of the
  last check), never silently treated as failures.
- An implemented availability policy (`historical/availability.py`,
  `HISTORICAL_AVAILABILITY_POLICY.md`) — `eligible_prior_starts()`
  returns a pitcher's own prior Final starts strictly before the target
  game's date, which is the dataset builder's actual leakage gate.
- An implemented `STRICT_LIVE_COMPATIBLE` training-dataset builder
  (`historical/dataset_builder.py`; CLI: `build-training-dataset`,
  `dataset-status`, `audit-training-dataset`, `export-training-dataset`)
  that reuses `features/expected_bf.py`/`features/builders.py`'s exact
  pure computation functions against availability-filtered historical
  inputs, per `TRAINING_DATASET_SPEC.md`. Covered by a dedicated leakage
  test suite (`engine/tests/integration/test_dataset_builder.py`) proving
  a row's features are built only from strictly-earlier Final starts for
  that same pitcher, never the target game itself or a later game.
- The permanent baseline model (`k-model-0.1.0`, `models/baseline.py`,
  unmodified) can be evaluated against a frozen dataset
  (`historical/evaluation.py`; CLI: `evaluate-baseline`) — MAE, RMSE,
  mean bias, Poisson deviance, and calibration/Brier score at 6
  illustrative half-integer thresholds (no real historical market lines
  exist, so "calibration" compares the model's own predicted P(over) to
  the realized frequency — see the module's docstring), broken out by
  `recent_k_rate_tier`. Covered by a hand-checkable unit-test suite
  (`engine/tests/unit/test_historical_evaluation.py`) with synthetic
  known-value assertions for every metric.
- A Poisson-regression challenger model
  (`historical/challenger_poisson.py`) — a log-link Poisson GLM fit via
  IRLS (`fit_poisson_regression`) over the same reduced feature set the
  baseline uses (`log1p(expected_bf)`, `recent_k_rate`, `rest_days` +
  missingness indicator), implementing the same `StrikeoutModel`
  interface as the baseline (ADR 0003) so the two are drop-in
  interchangeable. Needs the `training` extra (`numpy`; see
  `pyproject.toml` — kept out of the live pipeline's core dependencies,
  installed alongside `dev` in every environment that already installs
  `dev`). Covered by unit tests on synthetic data with a known generating
  relationship (`engine/tests/unit/test_challenger_poisson.py`).
- A time-ordered walk-forward validation harness
  (`historical/walk_forward.py`; CLI: `train-walk-forward-challenger`) —
  splits a dataset into N expanding-window folds (never k-fold
  cross-validation, which would leak future data into past folds), fits
  a fresh challenger on each fold's training rows only, and evaluates
  both the challenger and the baseline against that fold's validation
  rows. The core leakage guarantee (every fold's training rows are
  strictly earlier than its validation rows) has its own dedicated test
  (`engine/tests/unit/test_walk_forward.py`).
- **Real result from this session, full 2023-2025 backfill**
  (`cassandra build-training-dataset --seasons 2023,2024,2025` →
  14,578 rows → `cassandra train-walk-forward-challenger --dataset-id
  ... --n-folds 8`, 7 folds actually run, 1 skipped for insufficient
  early-season training data): the challenger beat the baseline on
  **every one of the 7 folds**:

  | fold | validation window | baseline MAE | challenger MAE |
  |------|--------------------|---------------|-----------------|
  | 1 | 2023-06-06 .. 2023-08-18 | 1.9601 | 1.8942 |
  | 2 | 2023-08-18 .. 2024-04-20 | 1.9267 | 1.8821 |
  | 3 | 2024-04-20 .. 2024-06-27 | 1.9260 | 1.8917 |
  | 4 | 2024-06-27 .. 2024-09-07 | 1.9463 | 1.8887 |
  | 5 | 2024-09-07 .. 2025-05-11 | 1.9188 | 1.8481 |
  | 6 | 2025-05-12 .. 2025-07-22 | 1.8583 | 1.8165 |
  | 7 | 2025-07-22 .. 2025-09-28 | 1.8854 | 1.8426 |

  Aggregate (row-weighted) MAE: baseline 1.9173, challenger 1.8663 — a
  consistent ~2.7% improvement across three full seasons and 14,578 real
  starts, not a fluke on one lucky fold or one partial dataset.
  `evaluate-baseline` against the same full dataset gave MAE 1.9223,
  RMSE 2.4254, mean bias -0.1102, mean Poisson deviance 1.3713, and
  calibration close to empirical at every threshold tested (e.g. line
  3.5: predicted P(over)=0.646 vs. empirical 0.676; line 8.5: predicted
  0.084 vs. empirical 0.081).
  (An earlier, smaller run against just 2023-2024's partial backfill —
  9,718 rows, 5 folds — showed the same ~2.7% gap, aggregate MAE 1.9311
  vs. 1.8790; kept here only as a note that the result replicated as
  more data came in, not as a separate finding.)

## Caveats on that result (read before treating it as a promotion case)

1. **Reduced feature set only.** Both models see the same 3 real
   predictors (`expected_bf`, `recent_k_rate`, `rest_days`) — no park
   factor, weather, opponent context, or pitch-level detail (Phase A
   items 6-10, not yet backfilled). The relative comparison is fair (both
   models are equally blind to the missing groups), but neither number
   represents what either model could do with the full feature set the
   product spec calls for.
2. **One fold count, one challenger family.** The ~2.7% MAE improvement
   replicated once as the dataset grew from 9,718 to 14,578 rows (same
   result, same direction, same rough magnitude), which is more than a
   single-run coincidence, but it's still one `--n-folds` choice and one
   model family (Poisson regression) -- not a robustness study across
   different fold counts, feature-engineering choices, or a
   negative-binomial alternative. Real but modest, and a real promotion
   decision should see more than this.
3. **No statistical-significance test.** The report gives per-fold and
   aggregate MAE, not a paired significance test (e.g. a paired
   bootstrap) on whether the gap is distinguishable from noise at this
   sample size.
4. **`STRICT_LIVE_COMPATIBLE`, not production-validated.** This dataset
   deliberately excludes lineup/park/weather features a promoted model
   would need to be checked against the *actual* live feature pipeline's
   real-time behavior (adapter failures, staleness, `MARKET_CONTEXT_
   INCOMPLETE` reason codes, etc.), which a backtest can't see.
5. **No automatic promotion exists, by design** — the mission directive
   is explicit that production promotion requires human approval, and no
   code path in this repository writes a challenger's predictions to
   `projections`/`grades` under any circumstance.

## What's still not built

1. **Player identity resolution hasn't run for backfilled pitchers** —
   `players` is empty in this pass, so pitcher handedness (a spec'd
   pregame feature) isn't available in any dataset row.
2. **A model registry.** Each walk-forward run writes its own frozen
   comparison-report JSON (versioned by dataset_id + model_version), but
   there's no index/registry tying multiple runs together, tracking
   shadow-mode status, or recording a promotion decision once a human
   makes one.
3. **Negative-binomial or gradient-boosted challengers** — only the
   Poisson-regression family has been implemented; the mission directive
   lists negative-binomial as an alternative worth trying (Poisson
   assumes variance equals the mean, which real strikeout counts may not
   satisfy exactly).
4. **Weather/park-factor/opponent-context backfill** (Phase A items
   6-10) — once collected, rebuild datasets with those groups populated
   and re-run both `evaluate-baseline` and
   `train-walk-forward-challenger` to see whether the ~2.7% gap widens,
   narrows, or reverses with richer features.
5. **Historical market-line hit rate** stays labeled "unavailable" unless
   genuine historical lines are imported separately (out of scope per the
   mission directive itself — a count model trains on actual strikeout
   outcomes, not market lines).

## Explicit statement

A real baseline evaluation and a real walk-forward challenger comparison
both exist now, with real numbers from real 2023-2024 backfill data (see
above). **No promotion, shadow-mode deployment, or production use of the
challenger model exists anywhere in this repository.** Nothing has been
written to the live `projections`/`grades` tables by anything other than
the live pipeline — every report this subsystem produces is labeled
`HISTORICAL_RECONSTRUCTION` and written to its own frozen file, never to
a live table. This report exists specifically so that fact is unambiguous
and checkable, not implied by silence.
