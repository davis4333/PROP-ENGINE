from __future__ import annotations

import math

import pytest

from cassandra.models.baseline import (
    MAX_CDF_K,
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


def test_poisson_strikeout_distribution_rejects_nan_mean():
    # Regression for a real numerical-edge-case finding: both
    # BaselinePoissonModel.predict() and PoissonRegressionModel.predict()
    # clip their computed mean with a plain min()/max(), but Python's
    # min()/max() silently pass NaN through unclipped -- so a malformed
    # feature value could previously reach here and silently produce a
    # distribution whose cdf() returns NaN, instead of failing loudly.
    with pytest.raises(ValueError, match="finite"):
        PoissonStrikeoutDistribution(mean=float("nan"))


def test_poisson_strikeout_distribution_rejects_infinite_mean():
    with pytest.raises(ValueError, match="finite"):
        PoissonStrikeoutDistribution(mean=float("inf"))


def test_poisson_strikeout_distribution_rejects_negative_mean():
    with pytest.raises(ValueError, match="non-negative"):
        PoissonStrikeoutDistribution(mean=-1.0)


def test_cdf_caps_absurdly_large_k_instead_of_hanging():
    # Regression for a real security-review finding: cdf(k) is an O(k)
    # pure-Python loop, and decision/engine.py derives k directly from a
    # market line (`math.floor(line)`) -- an unbounded/malformed line
    # (e.g. a fat-fingered admin import, or a malformed vendor response)
    # could otherwise make this loop run tens of millions of iterations.
    # A huge k must still return a sane probability near 1.0 fast, not
    # actually iterate that far.
    dist = PoissonStrikeoutDistribution(mean=6.0)
    assert dist.cdf(10_000_000) == pytest.approx(1.0, abs=1e-9)


def test_cdf_capped_value_matches_uncapped_for_a_realistic_mean():
    # The cap must not change the returned value for any real projection
    # -- confirm cdf(MAX_CDF_K) is already indistinguishable from the true
    # (uncapped, mathematically exact) limit of 1.0 for a typical mean.
    dist = PoissonStrikeoutDistribution(mean=6.0)
    assert dist.cdf(MAX_CDF_K) == pytest.approx(1.0, abs=1e-9)


def test_baseline_model_raises_loudly_rather_than_silently_producing_nan():
    # max()'s NaN-passthrough gotcha means MIN_PROJECTION_MEAN's clip
    # (`mean = max(mean, MIN_PROJECTION_MEAN)`) does not actually catch a
    # NaN recent_k_rate -- confirm the distribution constructor's guard
    # is what actually catches it, at the model's real entry point.
    with pytest.raises(ValueError, match="finite"):
        BaselinePoissonModel().predict(_features(expected_bf=22.0, recent_k_rate=float("nan")))
