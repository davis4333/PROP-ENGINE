"""Dispersion fitting for the negative-binomial challenger (mission
directive Phase 7: "at least one challenger count model... Poisson
regression, negative-binomial"). The mean regression itself reuses
`historical/challenger_poisson.py`'s existing IRLS fit UNCHANGED -- this
module adds only the one new piece: fitting `alpha` (the NB2 dispersion
parameter) by direct 1-D maximum-likelihood search given that
already-fitted, already-validated mean.

Deliberately NOT a joint two-parameter (coefficients + alpha) fit -- a
much larger, harder optimization problem than this needs. The diagnosed
problem (see `models/baseline.py`'s overdispersion finding,
`CURRENT_STATE_AUDIT.md`) is specifically about the *variance*
assumption; the mean regression was already proven (real walk-forward
evidence, a real paired-bootstrap significance test) to fit well on this
feature set, so holding it fixed and fitting only the added dispersion
parameter is the smallest correct fix, not an under-powered one.

`numpy` is this module's only dependency (see `pyproject.toml`'s
`training` extra) -- nothing outside `historical/` (training-only code)
imports this module, same pattern as `challenger_poisson.py`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from cassandra.historical.challenger_poisson import fit_poisson_regression
from cassandra.models.negative_binomial_regression import (
    NEGATIVE_BINOMIAL_CHALLENGER_VERSION,
    NegativeBinomialRegressionModel,
)

MIN_DISPERSION = 1e-6
MAX_DISPERSION = 10.0
_GOLDEN_SECTION_ITERATIONS = 80
_GOLDEN_RATIO = (math.sqrt(5) - 1) / 2


@dataclass(frozen=True)
class NegativeBinomialFitResult:
    """Deliberately the exact same shape as `challenger_poisson.py`'s
    `PoissonFitResult` (`.model`/`.converged`/`.n_iterations`) so both
    challenger families' fit functions are interchangeable in
    `walk_forward.py`'s dispatch table without family-specific branching.
    `.converged`/`.n_iterations` describe the underlying mean-regression
    IRLS fit -- the only iteratively-converged part of this fit; the
    dispersion parameter is found by a fixed-iteration golden-section
    search instead (see `.model`'s docstring for why this must never be
    silently indistinguishable from a converged fit)."""

    model: NegativeBinomialRegressionModel
    converged: bool
    n_iterations: int


def _negative_log_likelihood(alpha: float, means: np.ndarray, actuals: np.ndarray) -> float:
    """-log P(actuals | means, alpha) under the NB2 parameterization,
    summed over every row -- the exact same PMF math as
    NegativeBinomialStrikeoutDistribution._pmf, vectorized here for the
    search loop rather than constructing one distribution object per
    row per search iteration."""
    r = 1.0 / alpha
    lgamma_y_plus_r = np.array([math.lgamma(y + r) for y in actuals])
    lgamma_y_plus_1 = np.array([math.lgamma(y + 1) for y in actuals])
    # `- math.lgamma(r)` broadcasts across every row here; the final
    # np.sum() below then correctly applies it N times total (once per
    # row). An earlier version multiplied by len(actuals) here too,
    # double-counting N and applying an N^2 penalty -- caught by cross-
    # checking this MLE's result against a simple method-of-moments
    # estimate on the same data before trusting it (they should roughly
    # agree; they were off by ~29x, which is exactly this bug).
    log_lik = (
        lgamma_y_plus_r
        - math.lgamma(r)
        - lgamma_y_plus_1
        + actuals * np.log(means / (means + r))
        + r * np.log(r / (means + r))
    )
    return -float(np.sum(log_lik))


def _fit_dispersion(means: np.ndarray, actuals: np.ndarray) -> float:
    """Golden-section search for the alpha in [MIN_DISPERSION,
    MAX_DISPERSION] minimizing the NB2 negative log-likelihood -- a
    single-parameter, well-behaved (empirically unimodal on real
    overdispersed count data) search, no scipy/numpy-optimizer
    dependency needed for one parameter."""
    lo, hi = MIN_DISPERSION, MAX_DISPERSION
    c = hi - _GOLDEN_RATIO * (hi - lo)
    d = lo + _GOLDEN_RATIO * (hi - lo)
    f_c = _negative_log_likelihood(c, means, actuals)
    f_d = _negative_log_likelihood(d, means, actuals)
    for _ in range(_GOLDEN_SECTION_ITERATIONS):
        if f_c < f_d:
            hi, d, f_d = d, c, f_c
            c = hi - _GOLDEN_RATIO * (hi - lo)
            f_c = _negative_log_likelihood(c, means, actuals)
        else:
            lo, c, f_c = c, d, f_d
            d = lo + _GOLDEN_RATIO * (hi - lo)
            f_d = _negative_log_likelihood(d, means, actuals)
    return (lo + hi) / 2.0


def fit_negative_binomial_regression(rows: list[dict[str, Any]]) -> NegativeBinomialFitResult:
    """Fits the mean regression exactly as `fit_poisson_regression` does
    (same IRLS procedure, same coefficients -- calling it directly means
    any future change to that fit is picked up here automatically, never
    duplicated/re-derived), then fits one additional dispersion
    parameter (alpha) by 1-D MLE against that fixed mean. Raises
    ValueError on fewer than 10 rows via the same guard
    `fit_poisson_regression` already enforces."""
    poisson_fit = fit_poisson_regression(rows)

    means = np.array([poisson_fit.model.predict(r).mean for r in rows], dtype=float)
    actuals = np.array([float(r["actual_strikeouts"]) for r in rows], dtype=float)

    dispersion = _fit_dispersion(means, actuals)

    model = NegativeBinomialRegressionModel(
        coefficients=poisson_fit.model.coefficients, dispersion=dispersion
    )
    return NegativeBinomialFitResult(
        model=model,
        converged=poisson_fit.converged,
        n_iterations=poisson_fit.n_iterations,
    )


__all__ = [
    "MAX_DISPERSION",
    "MIN_DISPERSION",
    "NEGATIVE_BINOMIAL_CHALLENGER_VERSION",
    "NegativeBinomialFitResult",
    "NegativeBinomialRegressionModel",
    "fit_negative_binomial_regression",
]
