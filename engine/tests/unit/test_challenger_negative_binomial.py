"""historical/challenger_negative_binomial.py -- dispersion fitting
against synthetic overdispersed data with a known generating
relationship. Mirrors test_challenger_poisson.py's structure."""

from __future__ import annotations

import math
import random

from cassandra.historical.challenger_negative_binomial import (
    MAX_DISPERSION,
    MIN_DISPERSION,
    fit_negative_binomial_regression,
)


def _synthetic_overdispersed_rows(n: int, true_dispersion: float, seed: int = 0) -> list[dict]:
    """Generates rows from a KNOWN negative-binomial process (not just
    Poisson noise) -- the point of this fixture is to prove the fitted
    dispersion recovers something close to the true generating alpha,
    not just that the fit runs without crashing."""
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        expected_bf = rng.uniform(15, 28)
        recent_k_rate = rng.uniform(0.15, 0.32)
        rest_days = rng.choice([4, 5, 6, None])
        true_mean = max(expected_bf * recent_k_rate, 0.1)
        # Gamma-Poisson mixture -- the standard way to generate real NB2
        # data: draw a per-row rate from a Gamma with mean=true_mean,
        # shape=1/true_dispersion, then draw a Poisson count from that
        # rate. This is mathematically equivalent to sampling directly
        # from NB(true_mean, true_dispersion).
        shape = 1.0 / true_dispersion
        scale = true_mean / shape
        rate = rng.gammavariate(shape, scale)
        actual_strikeouts = rng.gauss(rate, math.sqrt(max(rate, 0.01)))  # Poisson approx via gauss
        rows.append(
            {
                "expected_bf": expected_bf,
                "recent_k_rate": recent_k_rate,
                "rest_days": rest_days,
                "actual_strikeouts": max(0, round(actual_strikeouts)),
            }
        )
    return rows


def test_fit_negative_binomial_regression_raises_on_too_few_rows():
    # Delegates straight to fit_poisson_regression's own row-count guard.
    rows = _synthetic_overdispersed_rows(5, true_dispersion=0.1)
    try:
        fit_negative_binomial_regression(rows)
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_fit_negative_binomial_regression_recovers_a_plausible_dispersion():
    rows = _synthetic_overdispersed_rows(2000, true_dispersion=0.15, seed=1)
    result = fit_negative_binomial_regression(rows)

    assert MIN_DISPERSION < result.model.dispersion < MAX_DISPERSION
    # Not an exact recovery (finite sample, Gauss-approximated Poisson
    # draws, and a fixed already-fitted mean rather than a joint fit),
    # but should land in the right ballpark of the true generating alpha.
    assert 0.03 < result.model.dispersion < 0.6


def test_fit_negative_binomial_regression_produces_reasonable_predictions():
    rows = _synthetic_overdispersed_rows(2000, true_dispersion=0.15, seed=2)
    result = fit_negative_binomial_regression(rows)
    model = result.model

    high = model.predict({"expected_bf": 27.0, "recent_k_rate": 0.30, "rest_days": 5})
    low = model.predict({"expected_bf": 16.0, "recent_k_rate": 0.16, "rest_days": 5})
    assert high.mean > low.mean

    typical = model.predict({"expected_bf": 22.0, "recent_k_rate": 0.22, "rest_days": 5})
    assert 1.0 < typical.mean < 12.0
    # Real overdispersion: this model's variance must exceed its mean,
    # unlike a Poisson-family model, which is the entire reason it exists.
    assert typical.sd**2 > typical.mean


def test_fit_negative_binomial_regression_reports_mean_regression_convergence():
    rows = _synthetic_overdispersed_rows(500, true_dispersion=0.15, seed=3)
    result = fit_negative_binomial_regression(rows)

    assert result.converged is True
    assert 0 < result.n_iterations <= 25


def test_fit_negative_binomial_regression_mean_matches_the_underlying_poisson_fit():
    # The mean regression is deliberately reused UNCHANGED from
    # fit_poisson_regression (see this module's docstring) -- confirm
    # the two fits genuinely produce identical coefficients on the same
    # data, not just similar ones.
    from cassandra.historical.challenger_poisson import fit_poisson_regression

    rows = _synthetic_overdispersed_rows(500, true_dispersion=0.15, seed=4)
    nb_result = fit_negative_binomial_regression(rows)
    poisson_result = fit_poisson_regression(rows)

    assert nb_result.model.coefficients == poisson_result.model.coefficients
