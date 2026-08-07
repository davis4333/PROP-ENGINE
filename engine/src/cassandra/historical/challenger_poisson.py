"""A Poisson-regression challenger model (mission directive Phase 7: "at
least one challenger count model... Poisson regression, negative-
binomial"), fit against a frozen `STRICT_LIVE_COMPATIBLE` training
dataset via `historical/walk_forward.py`.

Deliberately a *fitted* model, unlike the permanent baseline
(`models/baseline.py`'s `k-model-0.1.0`, a fixed formula never trained on
data) -- this is the actual point of comparison the directive asks for.
Implements `models.interface.StrikeoutModel`, so it's swappable anywhere
the baseline is (decision engine, evaluation harness) without either
depending on the other's implementation, per ADR 0003.

Uses plain IRLS (iteratively reweighted least squares) for a log-link
Poisson GLM rather than a heavier framework (statsmodels/sklearn) -- the
feature set here is small (3 numeric predictors), and IRLS for this
exact case is ~15 lines and easy to verify by hand. `numpy` is this
module's only dependency (see pyproject.toml's `training` extra); nothing
outside `historical/` imports this module, so the live pipeline/API never
needs numpy installed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from cassandra.models.baseline import PoissonStrikeoutDistribution
from cassandra.models.interface import StrikeoutDistribution, StrikeoutModel

POISSON_CHALLENGER_VERSION = "poisson-regression-challenger-0.1.0"

# Numeric predictors pulled from a dataset row (historical/dataset_
# builder.py's schema) -- deliberately the same reduced feature set the
# permanent baseline uses (expected_bf, recent_k_rate, rest_days), so a
# comparison between the two isn't confounded by one model simply having
# access to more inputs than the other.
DEFAULT_REST_DAYS = 5.0  # a typical starter's rest -- used only when rest_days is null
RIDGE_LAMBDA = 1.0
MAX_IRLS_ITERATIONS = 25
CONVERGENCE_TOL = 1e-8

# Names _design_row()'s positions, in order -- registry/service.py's
# durable model artifacts store fitted coefficients alongside this list
# (db/models/registry.py's `coefficient_order`) so a stored artifact is
# self-describing without needing this module's source to interpret it.
# Any change to _design_row's shape must update this tuple in lockstep --
# see tests/unit/test_challenger_poisson.py's coverage for the two
# staying in sync.
COEFFICIENT_NAMES = (
    "intercept",
    "log1p_expected_bf",
    "recent_k_rate",
    "rest_days",
    "rest_days_missing",
)


def _design_row(row: dict[str, Any]) -> list[float]:
    expected_bf = float(row.get("expected_bf") or 0.0)
    recent_k_rate = float(row.get("recent_k_rate") or 0.0)
    rest_days = row.get("rest_days")
    rest_days_value = float(rest_days) if rest_days is not None else DEFAULT_REST_DAYS
    rest_days_missing = 1.0 if rest_days is None else 0.0
    return [
        1.0,  # intercept
        math.log1p(max(expected_bf, 0.0)),
        recent_k_rate,
        rest_days_value,
        rest_days_missing,
    ]


def _design_matrix(rows: list[dict[str, Any]]) -> np.ndarray:
    return np.array([_design_row(r) for r in rows], dtype=float)


@dataclass(frozen=True)
class PoissonRegressionModel(StrikeoutModel):
    """A fitted Poisson-regression challenger. `coefficients` is the log-
    link GLM's beta vector, in the same order `_design_row` builds
    features -- `predict()` re-derives the identical design row for a
    single feature dict and applies `exp(X @ beta)`, so fit and predict
    can never drift out of sync with each other."""

    coefficients: tuple[float, ...]

    # Deliberately unannotated (not a dataclass field): StrikeoutModel
    # declares `model_version` as a ClassVar, and every instance of this
    # model shares the same version string regardless of its fitted
    # `coefficients` -- matching models/baseline.py's plain class-
    # attribute assignment rather than redeclaring it as a per-instance
    # dataclass field.
    model_version = POISSON_CHALLENGER_VERSION

    def predict(self, features: dict[str, Any]) -> StrikeoutDistribution:
        x = np.array(_design_row(features), dtype=float)
        beta = np.array(self.coefficients, dtype=float)
        eta = float(np.dot(x, beta))
        mean = math.exp(min(eta, 20.0))  # clip to avoid inf on a wild extrapolation
        return PoissonStrikeoutDistribution(mean=mean)


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
