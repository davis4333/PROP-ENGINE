"""IRLS fitting for the Poisson-regression challenger (mission directive
Phase 7: "at least one challenger count model... Poisson regression,
negative-binomial"), fit against a frozen `STRICT_LIVE_COMPATIBLE`
training dataset via `historical/walk_forward.py`.

The model class itself, `design_row()`/`COEFFICIENT_NAMES`, and the
actual `predict()` implementation live in `models/poisson_regression.py`
-- deliberately numpy-free so that module (and only that module) can be
imported from the live pipeline (`registry/service.py`'s
`resolve_active_model()`) without pulling `numpy` into the live
pipeline's core dependencies. This module re-exports everything from
there and adds the one thing that genuinely needs numpy: IRLS (iteratively
reweighted least squares) for the log-link Poisson GLM fit itself, rather
than a heavier framework (statsmodels/sklearn) -- the feature set here is
small (5 numeric predictors), and IRLS for this exact case is ~15 lines
and easy to verify by hand. `numpy` is this module's only dependency (see
pyproject.toml's `training` extra); nothing outside `historical/`
(training-only code) imports this module.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from cassandra.models.poisson_regression import (
    COEFFICIENT_NAMES,
    DEFAULT_REST_DAYS,
    POISSON_CHALLENGER_VERSION,
    PoissonRegressionModel,
    design_row,
)

RIDGE_LAMBDA = 1.0
MAX_IRLS_ITERATIONS = 25
CONVERGENCE_TOL = 1e-8


def _design_matrix(rows: list[dict[str, Any]]) -> np.ndarray:
    return np.array([design_row(r) for r in rows], dtype=float)


def fit_poisson_regression(rows: list[dict[str, Any]]) -> PoissonRegressionModel:
    """Fits a log-link Poisson GLM (`strikeouts ~ log1p(expected_bf) +
    recent_k_rate + rest_days`) via IRLS with a small ridge penalty (for
    numerical stability on modest per-fold sample sizes, not a tuned
    hyperparameter). Raises ValueError on fewer than 10 rows -- an IRLS
    fit on less data than that isn't a real regression, it's noise, and
    should fail loudly rather than silently return an unstable model.
    """
    if len(rows) < 10:
        raise ValueError(f"fit_poisson_regression needs at least 10 rows, got {len(rows)}")

    x = _design_matrix(rows)
    y = np.array([float(r["actual_strikeouts"]) for r in rows], dtype=float)
    n_features = x.shape[1]

    beta = np.zeros(n_features)
    ridge = RIDGE_LAMBDA * np.eye(n_features)

    for _ in range(MAX_IRLS_ITERATIONS):
        eta = x @ beta
        mu = np.exp(np.clip(eta, -20.0, 20.0))
        mu = np.clip(mu, 1e-6, None)
        working_response = eta + (y - mu) / mu
        xtwx = x.T @ (x * mu[:, None]) + ridge
        xtwz = x.T @ (mu * working_response)
        beta_new = np.linalg.solve(xtwx, xtwz)
        if np.max(np.abs(beta_new - beta)) < CONVERGENCE_TOL:
            beta = beta_new
            break
        beta = beta_new

    return PoissonRegressionModel(coefficients=tuple(float(b) for b in beta))


__all__ = [
    "COEFFICIENT_NAMES",
    "CONVERGENCE_TOL",
    "DEFAULT_REST_DAYS",
    "MAX_IRLS_ITERATIONS",
    "POISSON_CHALLENGER_VERSION",
    "RIDGE_LAMBDA",
    "PoissonRegressionModel",
    "fit_poisson_regression",
]
