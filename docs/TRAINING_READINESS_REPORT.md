# Training Readiness Report

**Status as of this pass: a real, leakage-tested training dataset can be
built and the permanent baseline (`k-model-0.1.0`, unchanged) can be
evaluated against it. No challenger model has been trained yet.** This is
a direct, honest statement, not a placeholder — see below for exactly
what's done, what's still blocking challenger training specifically, and
what a real run against real 2023 backfill data actually produced.

## What exists

- A resumable, idempotent historical backfill (`historical/backfill.py`)
  actually collecting real 2023-present MLB schedule/game, actual-starter,
  pitcher-outcome, and lineup data — see `HISTORICAL_COVERAGE_REPORT.md`
  / `audit-historical-coverage` for the current point-in-time coverage.
  2023 (regular season) is essentially complete; 2024 partial; 2025/2026
  not yet reached by this backfill pass.
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
- Verified against real backfill data in this session: building a
  `STRICT_LIVE_COMPATIBLE` dataset for season 2023 (`game_types=("R",)`)
  produced 4,860 real rows (`cassandra build-training-dataset --seasons
  2023`), with `recent_k_rate` tier counts `recent_weighted=4456,
  season_average=267, league_default=137` — i.e. the large majority of
  rows have enough real prior-start history for the live pipeline's own
  decay-weighted feature tier, not a fallback.
- The permanent baseline model (`k-model-0.1.0`, `models/baseline.py`,
  unmodified) can now be evaluated against a frozen dataset
  (`historical/evaluation.py`; CLI: `evaluate-baseline`) — MAE, RMSE,
  mean bias, Poisson deviance, and calibration/Brier score at 6
  illustrative half-integer thresholds (no real historical market lines
  exist, so "calibration" compares the model's own predicted P(over) to
  the realized frequency — see the module's docstring), broken out by
  `recent_k_rate_tier`. Every report is written
  `HISTORICAL_RECONSTRUCTION`-labeled to its own frozen JSON file, never
  to `projections`/`grades`. Covered by a hand-checkable unit-test suite
  (`engine/tests/unit/test_historical_evaluation.py`) with synthetic
  known-value assertions for every metric.
  **Real result from this session** (`cassandra evaluate-baseline
  --dataset-id <2023-season dataset>`, 4,860 real rows): MAE 1.95
  strikeouts, RMSE 2.47, mean bias -0.10 (slightly under-projects on
  average), mean Poisson deviance 1.43. Calibration was close across
  every threshold tested (e.g. line 3.5: predicted P(over)=0.647 vs.
  empirical 0.672; line 8.5: predicted 0.089 vs. empirical 0.088) — the
  baseline's probability estimates track realized outcomes reasonably
  well even on this reduced feature set, though this is one run against
  partial-season data, not a validated production-readiness claim.

## What's blocking challenger training specifically

1. **No challenger-training code exists yet.** Fitting a real Poisson
   regression or negative-binomial model (vs. the fixed-formula baseline)
   needs a numerical optimizer; this environment currently has no numpy/
   scipy/statsmodels installed, and adding a new dependency for a
   half-built feature wasn't done in this pass rather than rushing it.
   Walk-forward validation (train on earlier dates, validate on later
   ones, roll forward) also needs its own harness, separate from the
   dataset builder itself.
2. **Several pregame feature domains this backfill was scoped to collect
   aren't collected yet**: park factors calculated from prior games,
   historical weather, opponent rolling strikeout context, pitch-level
   detail (see `HISTORICAL_BACKFILL_DESIGN.md`'s "out of scope" list, and
   every dataset manifest's `excluded_feature_groups`). A first model
   comparison can reasonably proceed on the reduced feature set the
   builder already emits (recent K-rate, expected batters faced, rest
   days, identity) and report performance with-and-without the missing
   groups once they exist, per the mission directive's own evaluation
   requirements.
3. **The backfill itself is still running** (2024 partial, 2025/2026 not
   yet reached) — see `HISTORICAL_COVERAGE_REPORT.md`/
   `audit-historical-coverage` for exact current coverage. A dataset
   built today would need to honestly restrict `--seasons` to what's
   actually well-covered (2023, optionally partial 2024) — every manifest
   records exactly which seasons/game-types it drew from, so this is
   checkable, not implied.
4. **No player identity resolution has run for backfilled pitchers** —
   `players` is empty in this pass, so pitcher handedness (a spec'd
   pregame feature) isn't available; every dataset row is keyed by raw
   `player_mlb_id`/`team_mlb_id`/`opponent_mlb_id` integers instead.

## What happens next (not done in this pass)

1. Add a numerical-fitting dependency (numpy/scipy/statsmodels — a real
   decision, not silently picked) and train at least one challenger count
   model (Poisson regression, negative-binomial, or a gradient-boosted
   count model) using time-ordered walk-forward validation — train on
   earlier dates, validate on later dates, roll forward, never train on
   games after the evaluation game.
2. Produce a comparison report (challenger vs. the real baseline numbers
   above) and recommendation, plus a model registry entry. **No automatic
   promotion** — production promotion requires explicit human approval,
   per the mission directive.
3. Once weather/park-factor/opponent-context backfill exists (Phase A
   items 6-10), rebuild datasets with those groups populated and re-run
   `evaluate-baseline` to compare against the reduced-feature-set numbers
   above.
4. Historical market-line hit rate stays labeled "unavailable" unless
   genuine historical lines are imported separately (out of scope for
   this phase per the mission directive itself — a count model trains on
   actual strikeout outcomes, not market lines).

## Explicit statement

A real baseline evaluation now exists (`k-model-0.1.0` against a 2023-
season `STRICT_LIVE_COMPATIBLE` dataset, numbers above) — this is a
backtest/historical reconstruction, not a walk-forward validation (the
baseline is a fixed formula, not fit to any data, so there is no
train/test split to violate). **No challenger model has been trained,
and no walk-forward validation result exists anywhere in this
repository as of this pass.** Nothing has been written to the live
`projections`/`grades` tables by anything other than the live pipeline —
every evaluation report this module produces is labeled
`HISTORICAL_RECONSTRUCTION` and written to its own frozen file. This
report exists specifically so that fact is unambiguous and checkable,
not implied by silence.
