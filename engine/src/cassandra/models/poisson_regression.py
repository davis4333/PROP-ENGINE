"""The fitted Poisson-regression challenger model -- deliberately numpy-
free (a `design_row` dot product implemented in plain Python) so this
module can be safely imported and used from the LIVE pipeline
(`registry/service.py`'s `resolve_active_model()`, called from
`orchestration/run_slate.py`) without pulling `numpy` into the live
pipeline's core dependencies.

IRLS fitting (`fit_poisson_regression`) genuinely needs numpy and stays
in `historical/challenger_poisson.py` (training-only, `pyproject.toml`'s
`training` extra) -- that module imports everything from here and adds
fitting on top, re-exporting the combined set so every existing `from
cassandra.historical.challenger_poisson import ...` call site is
unaffected by this split. This module is the one source of truth for
`design_row()`/`COEFFICIENT_NAMES` and for how a fitted model actually
predicts -- both the training-time fit and a live-served reload always
go through the exact same `predict()` implementation, so they can never
drift apart.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from cassandra.models.baseline import PoissonStrikeoutDistribution
from cassandra.models.interface import StrikeoutDistribution, StrikeoutModel

POISSON_CHALLENGER_VERSION = "poisson-regression-challenger-0.1.0"

# Numeric predictors pulled from a dataset row (historical/dataset_
# builder.py's schema) or a live feature-values blob (features/builders.py)
# -- deliberately the same reduced feature set the permanent baseline
# uses (expected_bf, recent_k_rate, rest_days), so a comparison between
# the two isn't confounded by one model simply having access to more
# inputs than the other.
DEFAULT_REST_DAYS = 5.0  # a typical starter's rest -- used only when rest_days is null

# Names design_row()'s positions, in order -- registry/service.py's
# durable model artifacts store fitted coefficients alongside this list
# (db/models/registry.py's `coefficient_order`) so a stored artifact is
# self-describing without needing this module's source to interpret it.
# Any change to design_row's shape must update this tuple in lockstep --
# see tests/unit/test_challenger_poisson.py's coverage for the two
# staying in sync.
COEFFICIENT_NAMES = (
    "intercept",
    "log1p_expected_bf",
    "recent_k_rate",
    "rest_days",
    "rest_days_missing",
)


def design_row(row: dict[str, Any]) -> list[float]:
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


@dataclass(frozen=True)
class PoissonRegressionModel(StrikeoutModel):
    """A fitted Poisson-regression challenger. `coefficients` is the log-
    link GLM's beta vector, in the same order `design_row` builds
    features -- `predict()` re-derives the identical design row for a
    single feature dict and applies `exp(x . beta)`, so fit and predict
    can never drift out of sync with each other."""

    coefficients: tuple[float, ...]

    # Deliberately unannotated (not a dataclass field): StrikeoutModel
    # declares `model_version` as a ClassVar, and every instance of this
    # model shares the same version string regardless of its fitted
    # `coefficients` -- matching models/baseline.py's plain class-
    # attribute assignment rather than redeclaring it as a per-instance
    # dataclass field. A specific fitted artifact's own identity
    # (fitted_model_version, unique per artifact_id) is tracked
    # separately by the caller when publishing a projection -- see
    # registry/service.py's resolve_active_model().
    model_version = POISSON_CHALLENGER_VERSION

    def predict(self, features: dict[str, Any]) -> StrikeoutDistribution:
        x = design_row(features)
        eta = sum(xi * bi for xi, bi in zip(x, self.coefficients, strict=True))
        mean = math.exp(min(eta, 20.0))  # clip to avoid inf on a wild extrapolation
        return PoissonStrikeoutDistribution(mean=mean)


__all__ = [
    "COEFFICIENT_NAMES",
    "DEFAULT_REST_DAYS",
    "POISSON_CHALLENGER_VERSION",
    "PoissonRegressionModel",
    "design_row",
]
