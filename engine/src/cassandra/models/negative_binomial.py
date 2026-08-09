"""A negative-binomial strikeout distribution -- the distributional-
family fix for a real, measured problem: actual MLB strikeout counts are
overdispersed relative to a true Poisson (variance/mean = 1.30 on the
full 2023-2026 dataset, confirmed empirically -- see
CURRENT_STATE_AUDIT.md), which no Poisson-family model (variance = mean,
by construction) can represent. `models/baseline.py`'s
`PoissonStrikeoutDistribution` and every model built on it (the baseline
formula, `models/poisson_regression.py`'s GLM) hard-code variance =
mean; this class adds exactly one more parameter (dispersion, `alpha`)
that lets variance exceed the mean.

Standard NB2 GLM parameterization: mean = mu, variance = mu + alpha *
mu^2 (alpha > 0; smaller alpha approaches the Poisson case, but this
class requires alpha > 0 strictly -- use
`models.baseline.PoissonStrikeoutDistribution` directly for a true
Poisson rather than alpha=0 here, which is a divide-by-zero in this
class's internal (r, p) parameterization).

Deliberately numpy-free (same reasoning as `models/poisson_regression.py`
-- see that module's own docstring) so this class can be imported from
the live pipeline (`registry/service.py`'s `resolve_active_model()`)
without pulling numpy into the live pipeline's core dependencies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from cassandra.models.baseline import MAX_CDF_K


@dataclass(frozen=True)
class NegativeBinomialStrikeoutDistribution:
    """`mean`/`dispersion` (mu, alpha) are the NB2 GLM parameterization
    callers construct this with. Internally converted to the classic
    (r, p) "number of failures before the r-th success" parameterization
    for the actual PMF/CDF math: r = 1/alpha, p = r / (r + mu)."""

    mean: float
    dispersion: float

    def __post_init__(self) -> None:
        # Same reasoning as PoissonStrikeoutDistribution's own guard
        # (models/baseline.py, added after a numerical-edge-case stress
        # test): fail loudly on a non-finite/invalid parameter rather
        # than silently producing NaN downstream (CLAUDE.md: "Error/
        # stale-data behavior is visible... never a silent degradation").
        if not math.isfinite(self.mean) or self.mean < 0:
            raise ValueError(
                f"NegativeBinomialStrikeoutDistribution requires a finite, non-negative mean, "
                f"got {self.mean!r}"
            )
        if not math.isfinite(self.dispersion) or self.dispersion <= 0:
            raise ValueError(
                "NegativeBinomialStrikeoutDistribution requires a finite, positive dispersion "
                f"(alpha), got {self.dispersion!r} -- alpha must be > 0 (this class's (r, p) "
                "parameterization divides by alpha); use PoissonStrikeoutDistribution directly "
                "for a true Poisson rather than passing alpha=0 here"
            )

    @property
    def _r(self) -> float:
        return 1.0 / self.dispersion

    @property
    def _p(self) -> float:
        if self.mean == 0.0:
            return 1.0
        r = self._r
        return r / (r + self.mean)

    @property
    def sd(self) -> float:
        return math.sqrt(self.mean + self.dispersion * self.mean * self.mean)

    def cdf(self, k: int) -> float:
        """P(strikeouts <= k). `k` is capped at MAX_CDF_K for the same
        reason as PoissonStrikeoutDistribution.cdf() (models/baseline.py,
        found by an independent security review): an O(k) pure-Python
        loop must not be weaponizable by an unbounded/malformed line
        value."""
        if k < 0:
            return 0.0
        if self.mean == 0.0:
            return 1.0
        k = min(k, MAX_CDF_K)
        return sum(self._pmf(i) for i in range(k + 1))

    def _pmf(self, k: int) -> float:
        r = self._r
        p = self._p
        log_pmf = (
            math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + k * math.log1p(-p) + r * math.log(p)
        )
        return math.exp(log_pmf)


__all__ = ["NegativeBinomialStrikeoutDistribution"]
