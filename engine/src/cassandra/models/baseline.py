"""`k-model-0.1.0` -- the naive baseline strikeout model (BUILD_BACKLOG.csv
"P2 Strikeout Engine, 1, Naive baseline"). Deliberately a formula, not a
trained model: a genuinely simple, interpretable pre-comparison baseline,
not a preselected "winning" model family (handbook non-negotiable #7).

Formula:

    projection_mean = expected_bf * recent_k_rate * park_adj * weather_adj * opponent_adj

`park_adj`/`weather_adj`/`opponent_adj` are clipped to a bounded band so
a single noisy/extreme input can't blow up the projection. Strikeouts are
modeled as Poisson(projection_mean) -- one parameter, a natural fit for
count data, no separately-fit standard deviation needed
(`projection_sd = sqrt(mean)`, the Poisson variance).

Bumping `MODEL_VERSION` is the only sanctioned way to evolve this model --
once published, a projection's `model_version` is permanent (ADR 0010);
never change this formula's behavior in place under the same version
string.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from cassandra.models.interface import StrikeoutDistribution, StrikeoutModel

MODEL_VERSION = "k-model-0.1.0"

PARK_ADJ_BOUNDS = (0.85, 1.15)
WEATHER_ADJ_BOUNDS = (0.90, 1.10)
OPPONENT_ADJ_BOUNDS = (0.85, 1.15)
MIN_PROJECTION_MEAN = 0.05


@dataclass(frozen=True)
class PoissonStrikeoutDistribution:
    mean: float

    def __post_init__(self) -> None:
        # Both models that construct this (baseline's formula, the
        # challenger's log-link GLM) each clip their own computed mean
        # with a plain min()/max() -- but Python's min()/max() silently
        # pass NaN through unclipped (comparisons against NaN are always
        # False, a well-known gotcha), so a NaN/inf feature value could
        # otherwise reach here uncaught and silently produce NaN
        # probabilities downstream instead of a loud, immediate error.
        # Found by an explicit numerical-edge-case stress test, not
        # observed in real pipeline data -- features/builders.py's own
        # fallbacks (league-average constants) mean this shouldn't be
        # reachable via any real slate today, but a future feature/model
        # bug should fail loudly here rather than silently produce a
        # PoissonStrikeoutDistribution with cdf() returning NaN
        # (CLAUDE.md: "Error/stale-data behavior is visible... never a
        # silent degradation").
        if not math.isfinite(self.mean) or self.mean < 0:
            raise ValueError(
                f"PoissonStrikeoutDistribution requires a finite, non-negative mean, got {self.mean!r}"
            )

    @property
    def sd(self) -> float:
        return math.sqrt(self.mean)

    def cdf(self, k: int) -> float:
        """P(strikeouts <= k), the regular Poisson CDF."""
        if k < 0:
            return 0.0
        return sum(self._pmf(i) for i in range(k + 1))

    def _pmf(self, k: int) -> float:
        return math.exp(-self.mean + k * math.log(self.mean) - math.lgamma(k + 1))


def _clip(value: float, bounds: tuple[float, float]) -> float:
    lo, hi = bounds
    return max(lo, min(hi, value))


class BaselinePoissonModel(StrikeoutModel):
    model_version = MODEL_VERSION

    def predict(self, features: dict[str, Any]) -> StrikeoutDistribution:
        expected_bf = float(features.get("expected_bf", 0.0))
        recent_k_rate = float(features.get("recent_k_rate", 0.0))
        park_adj = _clip(float(features.get("park_k_factor", 1.0)), PARK_ADJ_BOUNDS)
        weather_adj = _clip(float(features.get("weather_adjustment", 1.0)), WEATHER_ADJ_BOUNDS)
        opponent_adj = _clip(float(features.get("opponent_adjustment", 1.0)), OPPONENT_ADJ_BOUNDS)

        mean = expected_bf * recent_k_rate * park_adj * weather_adj * opponent_adj
        mean = max(mean, MIN_PROJECTION_MEAN)
        return PoissonStrikeoutDistribution(mean=mean)
