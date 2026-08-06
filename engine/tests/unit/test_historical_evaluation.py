"""historical/evaluation.py -- pure metric computation against synthetic
rows and a fake deterministic model, so the numbers are hand-checkable."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from cassandra.historical.evaluation import CALIBRATION_THRESHOLDS, RECORD_LABEL, evaluate_model


@dataclass(frozen=True)
class _FixedDistribution:
    mean: float

    def cdf(self, k: int) -> float:
        """A degenerate point-mass-like CDF for test purposes: exact
        strikeout count is always `round(mean)`, so calibration at a
        threshold is fully deterministic and hand-checkable."""
        return 1.0 if k >= round(self.mean) else 0.0


class _FixedModel:
    model_version = "test-fixed-model-0.0.0"

    def __init__(self, mean: float) -> None:
        self._mean = mean

    def predict(self, features: dict[str, Any]) -> _FixedDistribution:
        return _FixedDistribution(mean=self._mean)


def test_evaluate_model_computes_mae_rmse_and_bias():
    rows = [
        {"actual_strikeouts": 5, "recent_k_rate_tier": "recent_weighted"},
        {"actual_strikeouts": 7, "recent_k_rate_tier": "recent_weighted"},
        {"actual_strikeouts": 3, "recent_k_rate_tier": "recent_weighted"},
    ]
    report = evaluate_model(rows, _FixedModel(mean=6.0), dataset_id="ds_test")

    # errors: 6-5=1, 6-7=-1, 6-3=3
    assert report.n_rows == 3
    assert report.n_rows_skipped_missing_label == 0
    assert report.mae == (1 + 1 + 3) / 3
    assert report.rmse == math.sqrt((1**2 + 1**2 + 3**2) / 3)
    assert report.mean_bias == (1 - 1 + 3) / 3
    assert report.record_label == RECORD_LABEL


def test_evaluate_model_skips_rows_with_missing_label_and_counts_them():
    rows = [
        {"actual_strikeouts": 5},
        {"actual_strikeouts": None},
    ]
    report = evaluate_model(rows, _FixedModel(mean=5.0), dataset_id="ds_test")

    assert report.n_rows == 1
    assert report.n_rows_skipped_missing_label == 1


def test_evaluate_model_poisson_deviance_is_zero_for_a_perfect_prediction():
    rows = [{"actual_strikeouts": 6}]
    report = evaluate_model(rows, _FixedModel(mean=6.0), dataset_id="ds_test")

    assert report.mean_poisson_deviance == 0.0


def test_evaluate_model_poisson_deviance_handles_zero_actual_without_raising():
    rows = [{"actual_strikeouts": 0}]
    report = evaluate_model(rows, _FixedModel(mean=3.0), dataset_id="ds_test")

    # deviance = 2 * (0 - (0 - 3)) = 6, no log(0) crash
    assert report.mean_poisson_deviance == 6.0


def test_evaluate_model_calibration_covers_every_configured_threshold():
    rows = [{"actual_strikeouts": 6}]
    report = evaluate_model(rows, _FixedModel(mean=6.0), dataset_id="ds_test")

    thresholds_seen = {c.threshold for c in report.calibration}
    assert thresholds_seen == set(CALIBRATION_THRESHOLDS)


def test_evaluate_model_calibration_reflects_perfectly_confident_correct_model():
    # _FixedDistribution with mean=6.0 puts P(X<=5)=0, P(X<=6)=1 -- so
    # P(over 5.5) = 1.0 (deterministically predicts strikeouts > 5.5).
    rows = [{"actual_strikeouts": 6}, {"actual_strikeouts": 6}]
    report = evaluate_model(rows, _FixedModel(mean=6.0), dataset_id="ds_test")

    line_5_5 = next(c for c in report.calibration if c.threshold == 5.5)
    assert line_5_5.mean_predicted_prob_over == 1.0
    assert line_5_5.empirical_over_rate == 1.0
    assert line_5_5.brier_score == 0.0  # perfectly calibrated on this synthetic case

    line_7_5 = next(c for c in report.calibration if c.threshold == 7.5)
    assert line_7_5.mean_predicted_prob_over == 0.0
    assert line_7_5.empirical_over_rate == 0.0
    assert line_7_5.brier_score == 0.0


def test_evaluate_model_breaks_down_mae_by_recent_k_rate_tier():
    rows = [
        {"actual_strikeouts": 5, "recent_k_rate_tier": "recent_weighted"},
        {"actual_strikeouts": 9, "recent_k_rate_tier": "league_default"},
    ]
    report = evaluate_model(rows, _FixedModel(mean=6.0), dataset_id="ds_test")

    assert report.breakdown_by_recent_k_rate_tier["recent_weighted"] == {"n": 1, "mae": 1.0}
    assert report.breakdown_by_recent_k_rate_tier["league_default"] == {"n": 1, "mae": 3.0}
