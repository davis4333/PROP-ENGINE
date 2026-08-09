"""models/negative_binomial.py -- NegativeBinomialStrikeoutDistribution's
PMF/CDF correctness, its guard rails, and its Poisson-limit sanity check
(the whole point of this distribution family is to add variance on top
of a Poisson-shaped mean -- as dispersion shrinks to near zero, it should
behave almost identically to a true Poisson with the same mean)."""

from __future__ import annotations

import math

import pytest

from cassandra.models.baseline import MAX_CDF_K, PoissonStrikeoutDistribution
from cassandra.models.negative_binomial import NegativeBinomialStrikeoutDistribution


def test_rejects_nan_mean():
    with pytest.raises(ValueError, match="finite"):
        NegativeBinomialStrikeoutDistribution(mean=float("nan"), dispersion=0.1)


def test_rejects_infinite_mean():
    with pytest.raises(ValueError, match="finite"):
        NegativeBinomialStrikeoutDistribution(mean=float("inf"), dispersion=0.1)


def test_rejects_negative_mean():
    with pytest.raises(ValueError, match="non-negative"):
        NegativeBinomialStrikeoutDistribution(mean=-1.0, dispersion=0.1)


def test_rejects_zero_dispersion():
    # alpha=0 is a divide-by-zero in this class's (r, p) parameterization
    # -- use PoissonStrikeoutDistribution directly for a true Poisson.
    with pytest.raises(ValueError, match="positive dispersion"):
        NegativeBinomialStrikeoutDistribution(mean=5.0, dispersion=0.0)


def test_rejects_negative_dispersion():
    with pytest.raises(ValueError, match="positive dispersion"):
        NegativeBinomialStrikeoutDistribution(mean=5.0, dispersion=-0.1)


def test_rejects_nan_dispersion():
    with pytest.raises(ValueError, match="positive dispersion"):
        NegativeBinomialStrikeoutDistribution(mean=5.0, dispersion=float("nan"))


def test_variance_exceeds_a_poisson_with_the_same_mean():
    # The entire point of this distribution: variance = mean + alpha *
    # mean^2 > mean, unlike PoissonStrikeoutDistribution's mean=variance.
    dist = NegativeBinomialStrikeoutDistribution(mean=5.0, dispersion=0.1)
    variance = dist.sd**2
    assert variance > 5.0
    assert variance == pytest.approx(5.0 + 0.1 * 5.0**2)


def test_cdf_is_a_valid_distribution():
    dist = NegativeBinomialStrikeoutDistribution(mean=5.0, dispersion=0.1)
    assert dist.cdf(-1) == 0.0
    # <= 1.0 + a small floating-point tolerance -- summing many small PMF
    # terms accumulates a tiny amount of error (cdf(50) lands a few ulps
    # above exactly 1.0), same property any such summed-CDF has.
    assert 0.0 <= dist.cdf(3) <= dist.cdf(10) <= dist.cdf(50) <= 1.0 + 1e-9
    assert dist.cdf(500) == pytest.approx(1.0, abs=1e-6)


def test_cdf_caps_absurdly_large_k_instead_of_hanging():
    # Same defense as PoissonStrikeoutDistribution.cdf() (models/
    # baseline.py, found by an independent security review) -- an
    # unbounded/malformed line value must not be able to weaponize this
    # O(k) loop.
    dist = NegativeBinomialStrikeoutDistribution(mean=5.0, dispersion=0.1)
    assert dist.cdf(10_000_000) == pytest.approx(1.0, abs=1e-6)
    assert dist.cdf(MAX_CDF_K) == pytest.approx(dist.cdf(10_000_000), abs=1e-9)


def test_zero_mean_is_a_degenerate_point_mass_at_zero():
    dist = NegativeBinomialStrikeoutDistribution(mean=0.0, dispersion=0.1)
    assert dist.cdf(0) == 1.0
    assert dist.cdf(5) == 1.0
    assert dist.cdf(-1) == 0.0


@pytest.mark.parametrize("mean", [1.0, 5.0, 12.0])
def test_approaches_a_poisson_with_the_same_mean_as_dispersion_shrinks(mean):
    # As alpha -> 0, the NB2 distribution's variance (mean + alpha*mean^2)
    # approaches the Poisson variance (mean) -- confirm the CDFs converge
    # too, not just the variance formula, as a real end-to-end sanity
    # check on the PMF math itself.
    poisson = PoissonStrikeoutDistribution(mean=mean)
    nb = NegativeBinomialStrikeoutDistribution(mean=mean, dispersion=1e-5)
    for k in range(0, 15):
        assert nb.cdf(k) == pytest.approx(poisson.cdf(k), abs=1e-3)


def test_pmf_sums_to_one_across_a_wide_range():
    dist = NegativeBinomialStrikeoutDistribution(mean=6.0, dispersion=0.3)
    total = sum(dist._pmf(k) for k in range(0, 400))
    assert total == pytest.approx(1.0, abs=1e-6)


def test_sd_matches_manual_variance_formula():
    dist = NegativeBinomialStrikeoutDistribution(mean=4.8, dispersion=0.025)
    expected_variance = 4.8 + 0.025 * 4.8 * 4.8
    assert dist.sd == pytest.approx(math.sqrt(expected_variance))
