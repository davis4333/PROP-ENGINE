"""A negative-binomial regression challenger -- the SAME mean function as
`models/poisson_regression.py`'s `PoissonRegressionModel` (identical
`design_row()`/coefficients, reused directly rather than re-derived),
wrapped in a `NegativeBinomialStrikeoutDistribution` instead of a Poisson
one. Fixes a real, measured problem: the existing Poisson-family
challenger's mean was already validated (real walk-forward evidence, a
real paired-bootstrap significance test) -- what was wrong was the
*variance* assumption, not the mean, so this deliberately reuses that
proven mean regression and adds only the one missing piece: a real
dispersion parameter fit from actual data.

Deliberately numpy-free (same reasoning as `poisson_regression.py`) so
this module can be imported from the live pipeline (`registry/
service.py`'s `resolve_active_model()`) without pulling numpy into the
live pipeline's core dependencies. Fitting -- reusing
`historical/challenger_poisson.py`'s existing IRLS mean fit, then fitting
the one additional dispersion parameter -- lives in
`historical/challenger_negative_binomial.py` (training-only, needs
numpy).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from cassandra.models.interface import StrikeoutDistribution, StrikeoutModel
from cassandra.models.negative_binomial import NegativeBinomialStrikeoutDistribution
from cassandra.models.poisson_regression import design_row

NEGATIVE_BINOMIAL_CHALLENGER_VERSION = "negative-binomial-regression-challenger-0.1.0"


@dataclass(frozen=True)
class NegativeBinomialRegressionModel(StrikeoutModel):
    """A fitted negative-binomial regression challenger. `coefficients`
    is the identical log-link mean regression `PoissonRegressionModel`
    uses (same `design_row()` order); `dispersion` is the one additional
    fitted parameter (alpha) controlling how much extra variance sits on
    top of that mean."""

    coefficients: tuple[float, ...]
    dispersion: float

    # Deliberately unannotated (not a dataclass field) -- same reasoning
    # as PoissonRegressionModel's own model_version: StrikeoutModel
    # declares it as a ClassVar, shared across every instance regardless
    # of fitted parameters.
    model_version = NEGATIVE_BINOMIAL_CHALLENGER_VERSION

    def predict(self, features: dict[str, Any]) -> StrikeoutDistribution:
        x = design_row(features)
        eta = sum(xi * bi for xi, bi in zip(x, self.coefficients, strict=True))
        mean = math.exp(min(eta, 20.0))  # same extrapolation clip as PoissonRegressionModel
        return NegativeBinomialStrikeoutDistribution(mean=mean, dispersion=self.dispersion)


__all__ = ["NEGATIVE_BINOMIAL_CHALLENGER_VERSION", "NegativeBinomialRegressionModel"]
