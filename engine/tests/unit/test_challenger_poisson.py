"""historical/challenger_poisson.py -- IRLS fit correctness against
synthetic data with a known generating relationship, and basic sanity
checks on the fitted model's predictions."""

from __future__ import annotations

import math
import random

from cassandra.historical.challenger_poisson import fit_poisson_regression


def _synthetic_rows(n: int, seed: int = 0) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        expected_bf = rng.uniform(15, 28)
        recent_k_rate = rng.uniform(0.15, 0.32)
        rest_days = rng.choice([4, 5, 6, None])
        # True generating mean: strikeouts scale with expected_bf * k_rate,
        # matching the same intuition the permanent baseline formula uses.
        true_mean = max(expected_bf * recent_k_rate, 0.1)
        actual_strikeouts = rng.gauss(true_mean, math.sqrt(true_mean))
        rows.append(
            {
                "expected_bf": expected_bf,
                "recent_k_rate": recent_k_rate,
                "rest_days": rest_days,
                "actual_strikeouts": max(0, round(actual_strikeouts)),
            }
        )
    return rows


def test_fit_poisson_regression_raises_on_too_few_rows():
    rows = _synthetic_rows(5)
    try:
        fit_poisson_regression(rows)
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_fit_poisson_regression_produces_reasonable_predictions_on_synthetic_data():
    train_rows = _synthetic_rows(500, seed=1)
    fit_result = fit_poisson_regression(train_rows)
    model = fit_result.model

    # A pitcher with a high expected_bf and high K rate should get a
    # meaningfully higher projection than one with low values on both --
    # basic monotonicity sanity check, not a precision claim.
    high = model.predict({"expected_bf": 27.0, "recent_k_rate": 0.30, "rest_days": 5})
    low = model.predict({"expected_bf": 16.0, "recent_k_rate": 0.16, "rest_days": 5})
    assert high.mean > low.mean

    # Predictions should land in a plausible strikeout range, not blow up
    # or collapse to near-zero, on inputs drawn from the same
    # distribution the model was trained on.
    typical = model.predict({"expected_bf": 22.0, "recent_k_rate": 0.22, "rest_days": 5})
    assert 1.0 < typical.mean < 12.0


def test_fit_poisson_regression_handles_missing_rest_days_without_raising():
    rows = _synthetic_rows(200, seed=2)
    model = fit_poisson_regression(rows).model

    result = model.predict({"expected_bf": 22.0, "recent_k_rate": 0.22, "rest_days": None})
    assert result.mean > 0


def test_fit_poisson_regression_cdf_is_a_valid_distribution():
    rows = _synthetic_rows(200, seed=3)
    model = fit_poisson_regression(rows).model
    distribution = model.predict({"expected_bf": 22.0, "recent_k_rate": 0.22, "rest_days": 5})

    assert distribution.cdf(-1) == 0.0
    assert 0.0 <= distribution.cdf(3) <= distribution.cdf(10) <= 1.0


def test_fit_poisson_regression_reports_convergence_on_well_posed_data():
    # 200 rows / 5 features / well-conditioned design -- IRLS should
    # converge comfortably within MAX_IRLS_ITERATIONS on data like this.
    rows = _synthetic_rows(200, seed=4)
    fit_result = fit_poisson_regression(rows)

    assert fit_result.converged is True
    assert 0 < fit_result.n_iterations <= 25
