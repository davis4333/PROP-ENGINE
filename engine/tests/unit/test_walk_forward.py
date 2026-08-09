"""historical/walk_forward.py -- the core guarantee this module exists
for: every fold's training rows are strictly earlier than every row in
that fold's own validation set. Also covers run_walk_forward_validation's
end-to-end wiring against synthetic rows large enough to actually fit."""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

import pytest

from cassandra.historical.walk_forward import (
    MIN_TRAIN_ROWS,
    build_expanding_folds,
    run_walk_forward_validation,
)
from cassandra.models.baseline import BaselinePoissonModel
from cassandra.models.poisson_regression import PoissonRegressionModel


def _rows_across_dates(n: int, start: date, seed: int = 0) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        game_date = (start + timedelta(days=i // 5)).isoformat()  # ~5 starts/day across the slate
        expected_bf = rng.uniform(15, 28)
        recent_k_rate = rng.uniform(0.15, 0.32)
        true_mean = max(expected_bf * recent_k_rate, 0.1)
        rows.append(
            {
                "game_date": game_date,
                "expected_bf": expected_bf,
                "recent_k_rate": recent_k_rate,
                "recent_k_rate_tier": "recent_weighted",
                "rest_days": 5,
                "actual_strikeouts": max(0, round(rng.gauss(true_mean, math.sqrt(true_mean)))),
            }
        )
    return rows


def test_build_expanding_folds_never_trains_on_a_date_at_or_after_validation():
    rows = _rows_across_dates(300, date(2023, 4, 1))
    folds = build_expanding_folds(rows, n_folds=5)

    assert len(folds) == 5
    for train, validation in folds:
        if not train:
            continue
        max_train_date = max(r["game_date"] for r in train)
        min_validation_date = min(r["game_date"] for r in validation)
        assert max_train_date < min_validation_date


def test_build_expanding_folds_training_set_grows_across_folds():
    rows = _rows_across_dates(300, date(2023, 4, 1))
    folds = build_expanding_folds(rows, n_folds=5)

    train_sizes = [len(train) for train, _ in folds]
    assert train_sizes == sorted(train_sizes)  # non-decreasing -- expanding window


def test_build_expanding_folds_returns_empty_for_no_rows():
    assert build_expanding_folds([], n_folds=5) == []


def test_run_walk_forward_validation_skips_folds_with_insufficient_training_data():
    # Fewer rows than MIN_TRAIN_ROWS in total -- every fold's training set
    # will be too small to fit, so all folds should be skipped, not
    # crash or silently fit on noise.
    rows = _rows_across_dates(50, date(2023, 4, 1))
    result = run_walk_forward_validation(rows, dataset_id="ds_test", n_folds=5)

    assert result.n_folds == 0
    assert result.n_folds_skipped_insufficient_train_data > 0


def test_run_walk_forward_validation_produces_comparable_baseline_and_challenger_reports():
    # Enough rows that later folds have >= MIN_TRAIN_ROWS of training data.
    rows = _rows_across_dates(MIN_TRAIN_ROWS * 6, date(2023, 4, 1), seed=7)
    result = run_walk_forward_validation(rows, dataset_id="ds_test", n_folds=5)

    assert result.n_folds > 0
    for fold in result.folds:
        assert fold.train_n >= MIN_TRAIN_ROWS
        assert fold.baseline_report.n_rows == fold.validation_n
        assert fold.challenger_report.n_rows == fold.validation_n
        assert fold.train_end_date < fold.validation_start_date
    assert result.aggregate_baseline_mae >= 0
    assert result.aggregate_challenger_mae >= 0


def test_run_walk_forward_validation_aggregates_tier_breakdown_from_held_out_rows_only():
    # Every synthetic row is tagged "recent_weighted" -- the aggregated
    # tier breakdown should report that single tier, with a row count
    # equal to the sum of every fold's *validation* rows only (never
    # including any fold's training rows), so this can never be mistaken
    # for the in-sample breakdown historical/evaluation.py produces.
    rows = _rows_across_dates(MIN_TRAIN_ROWS * 6, date(2023, 4, 1), seed=7)
    result = run_walk_forward_validation(rows, dataset_id="ds_test", n_folds=5)

    total_validation_n = sum(fold.validation_n for fold in result.folds)

    for breakdown in (result.aggregate_baseline_tier_breakdown, result.aggregate_challenger_tier_breakdown):
        assert set(breakdown.keys()) == {"recent_weighted"}
        assert breakdown["recent_weighted"]["n"] == total_validation_n
        assert breakdown["recent_weighted"]["mae"] >= 0


def test_run_walk_forward_validation_rejects_an_unsupported_family():
    rows = _rows_across_dates(MIN_TRAIN_ROWS * 6, date(2023, 4, 1), seed=7)
    with pytest.raises(ValueError, match="unsupported family"):
        run_walk_forward_validation(rows, dataset_id="ds_test", n_folds=5, family="some-future-family")


def test_run_walk_forward_validation_supports_the_negative_binomial_family():
    rows = _rows_across_dates(MIN_TRAIN_ROWS * 6, date(2023, 4, 1), seed=7)
    result = run_walk_forward_validation(
        rows, dataset_id="ds_test", n_folds=5, family="negative-binomial-regression"
    )

    assert result.n_folds > 0
    assert result.challenger_model_version == "negative-binomial-regression-challenger-0.1.0"
    assert result.aggregate_challenger_mae >= 0
    # A real, distinct fit -- not accidentally reusing the Poisson
    # challenger's numbers, even though both share the same mean
    # regression (they can legitimately match closely, but the
    # model_version above already proves this ran the NB code path).
    for fold in result.folds:
        assert fold.challenger_converged is True


def test_run_walk_forward_validation_without_an_active_model_leaves_active_fields_none():
    # The common bootstrapping case: nothing has ever been promoted.
    rows = _rows_across_dates(MIN_TRAIN_ROWS * 6, date(2023, 4, 1), seed=7)
    result = run_walk_forward_validation(rows, dataset_id="ds_test", n_folds=5)

    assert result.active_model_version is None
    assert result.aggregate_active_mae is None
    for fold in result.folds:
        assert fold.active_report is None


def test_run_walk_forward_validation_evaluates_a_real_active_model_per_fold():
    # Regression for a real gap: a candidate must be judged against BOTH
    # the permanent baseline AND whatever Cassandra is currently serving
    # live predictions with -- not just the baseline. Uses a real fitted
    # PoissonRegressionModel as a stand-in "currently active" model
    # (structurally identical to what registry.service.
    # resolve_active_model() would hand this function in production) and
    # confirms it's evaluated -- fresh, never refit -- against every
    # fold's real held-out validation rows.
    rows = _rows_across_dates(MIN_TRAIN_ROWS * 6, date(2023, 4, 1), seed=7)
    active_model = PoissonRegressionModel(coefficients=(0.5, 0.1, 2.0, -0.02, 0.0))

    result = run_walk_forward_validation(
        rows,
        dataset_id="ds_test",
        n_folds=5,
        active_model=active_model,
        active_model_version="poisson-regression-challenger-0.1.0+artifact_test_active",
    )

    assert result.active_model_version == "poisson-regression-challenger-0.1.0+artifact_test_active"
    assert result.aggregate_active_mae is not None
    assert result.aggregate_active_mae >= 0
    for fold in result.folds:
        assert fold.active_report is not None
        assert fold.active_report.n_rows == fold.validation_n
        assert fold.active_report.model_version == active_model.model_version


def test_run_walk_forward_validation_active_model_is_not_refit_per_fold():
    # The active model is a FIXED, already-fitted artifact -- unlike the
    # challenger, which genuinely refits fresh on each fold's expanding
    # training window, the same active_model object/coefficients must be
    # what's evaluated in every fold (re-fitting it would defeat the
    # entire point: it's not a candidate being trained, it's what's
    # already live).
    rows = _rows_across_dates(MIN_TRAIN_ROWS * 6, date(2023, 4, 1), seed=7)
    active_model = BaselinePoissonModel()

    result = run_walk_forward_validation(
        rows, dataset_id="ds_test", n_folds=5, active_model=active_model, active_model_version="k-model-0.1.0"
    )

    for fold in result.folds:
        assert fold.active_report.model_version == "k-model-0.1.0"
    # BaselinePoissonModel's predictions are a pure function of features
    # (no fitted state at all) -- its aggregate MAE across every held-out
    # fold must be identical whether it's passed as the "active" model
    # here or evaluated directly as the baseline, proving no fold-
    # specific refitting/mutation happened to it.
    assert result.aggregate_active_mae == result.aggregate_baseline_mae
