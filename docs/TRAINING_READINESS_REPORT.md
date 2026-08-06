# Training Readiness Report

**Status as of this pass: a real, leakage-tested training dataset can now
be built (`STRICT_LIVE_COMPATIBLE`, reduced feature set). No model has
been trained or evaluated against it yet.** This is a direct, honest
statement, not a placeholder — see below for exactly what's done, what's
blocking evaluation/training specifically, and what a run against real
2023 backfill data actually produced.

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
- The permanent baseline model (`k-model-0.1.0`, `models/baseline.py`)
  already exists and runs live — but it has never been evaluated against
  this or any historical dataset, only against live slates as they occur.

## What's blocking evaluation/training specifically

1. **No evaluation/training code exists yet.** The dataset builder
   produces frozen feature+label rows; nothing yet loads one, runs
   `k-model-0.1.0`'s Poisson formula against it, or computes MAE/RMSE/
   calibration/Brier score. This is the next real engineering task, not
   done in this pass.
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

1. Build the actual baseline evaluation: load a dataset's JSONL rows, run
   `k-model-0.1.0` against each row's features, compute MAE, RMSE, mean
   bias, Poisson deviance, calibration at common half-lines, Brier score
   — broken out by season/sample-size tier, with and without optional
   feature groups once available.
2. Train at least one challenger count model (Poisson regression,
   negative-binomial, or a gradient-boosted count model) using
   time-ordered walk-forward validation — train on earlier dates,
   validate on later dates, roll forward, never train on games after the
   evaluation game.
3. Produce a comparison report and recommendation, and a model registry
   entry. **No automatic promotion** — production promotion requires
   explicit human approval, per the mission directive.
4. Once weather/park-factor/opponent-context backfill exists (Phase A
   items 6-10), rebuild datasets with those groups populated and compare
   against the reduced-feature-set baseline.
5. Historical market-line hit rate stays labeled "unavailable" unless
   genuine historical lines are imported separately (out of scope for
   this phase per the mission directive itself — a count model trains on
   actual strikeout outcomes, not market lines).

## Explicit statement

No historical model evaluation, backtest, or walk-forward result exists
anywhere in this repository as of this pass — a training dataset can now
be built and frozen, but nothing has read one back to evaluate or train a
model yet. Nothing has been written to the live `projections`/`grades`
tables by anything other than the live pipeline. This report exists
specifically so that fact is unambiguous and checkable, not implied by
silence.
