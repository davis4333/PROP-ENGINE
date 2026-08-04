from __future__ import annotations

import math

import pytest

from cassandra.models.baseline import (
    MIN_PROJECTION_MEAN,
    BaselinePoissonModel,
    PoissonStrikeoutDistribution,
)


def _reference_poisson_cdf(mean: float, k: int) -> float:
    """Straightforward (non-log-space) reference implementation to
    cross-check the lgamma-based one against, for small k where overflow
    isn't a concern."""
    if k < 0:
        return 0.0
    return sum(math.exp(-mean) * mean**i / math.factorial(i) for i in range(k + 1))


@pytest.mark.parametrize("mean", [0.5, 3.2, 6.1, 12.0])
@pytest.mark.parametrize("k", [0, 1, 3, 5, 10, 15])
def test_poisson_cdf_matches_reference_implementation(mean: float, k: int):
    dist = PoissonStrikeoutDistribution(mean=mean)
    assert dist.cdf(k) == pytest.approx(_reference_poisson_cdf(mean, k), abs=1e-9)


def test_poisson_cdf_negative_k_is_zero():
    assert PoissonStrikeoutDistribution(mean=5.0).cdf(-1) == 0.0


def test_poisson_cdf_monotonically_increasing():
    dist = PoissonStrikeoutDistribution(mean=6.0)
    values = [dist.cdf(k) for k in range(15)]
    assert values == sorted(values)


def test_poisson_cdf_approaches_one():
    dist = PoissonStrikeoutDistribution(mean=6.0)
    assert dist.cdf(50) == pytest.approx(1.0, abs=1e-9)


def test_poisson_sd_is_sqrt_mean():
    dist = PoissonStrikeoutDistribution(mean=9.0)
    assert dist.sd == pytest.approx(3.0)


# --- BaselinePoissonModel -----------------------------------------------


def _features(**overrides) -> dict:
    base = {
        "expected_bf": 23.0,
        "recent_k_rate": 0.25,
        "park_k_factor": 1.00,
        "weather_adjustment": 1.00,
        "opponent_adjustment": 1.00,
    }
    base.update(overrides)
    return base


def test_baseline_model_neutral_inputs():
    dist = BaselinePoissonModel().predict(_features())
    assert dist.mean == pytest.approx(23.0 * 0.25)


def test_baseline_model_park_adjustment_applied():
    dist = BaselinePoissonModel().predict(_features(park_k_factor=1.10))
    assert dist.mean == pytest.approx(23.0 * 0.25 * 1.10)


def test_baseline_model_clips_extreme_park_factor():
    # 2.0 is absurd -- must clip to the upper bound, not apply it raw.
    dist_extreme = BaselinePoissonModel().predict(_features(park_k_factor=2.0))
    dist_at_bound = BaselinePoissonModel().predict(_features(park_k_factor=1.15))
    assert dist_extreme.mean == pytest.approx(dist_at_bound.mean)


def test_baseline_model_clips_extreme_weather():
    dist_extreme = BaselinePoissonModel().predict(_features(weather_adjustment=5.0))
    dist_at_bound = BaselinePoissonModel().predict(_features(weather_adjustment=1.10))
    assert dist_extreme.mean == pytest.approx(dist_at_bound.mean)


def test_baseline_model_missing_features_use_neutral_defaults_not_raise():
    dist = BaselinePoissonModel().predict({"expected_bf": 20.0, "recent_k_rate": 0.2})
    assert dist.mean == pytest.approx(20.0 * 0.2)


def test_baseline_model_never_produces_zero_or_negative_mean():
    dist = BaselinePoissonModel().predict(_features(expected_bf=0.0, recent_k_rate=0.0))
    assert dist.mean == MIN_PROJECTION_MEAN


def test_baseline_model_version_is_pinned():
    assert BaselinePoissonModel.model_version == "k-model-0.1.0"
