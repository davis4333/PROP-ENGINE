"""The model interface (ADR 0003 / CLAUDE.md do-not-do list): the
decision engine must only ever call `StrikeoutModel.predict()` and the
returned `StrikeoutDistribution`'s `mean`/`cdf()` -- never assume a
specific distributional family. `k-model-0.1.0` (models/baseline.py) is a
Poisson implementation, but this interface is written so a future
negative-binomial, simulation-based, or trained model is a drop-in
replacement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Protocol


class StrikeoutDistribution(Protocol):
    """Whatever a model returns must satisfy this -- a mean and a CDF.
    That's the entire contract the decision engine is allowed to use.

    `mean` is a read-only property (not a plain attribute) so frozen
    dataclasses -- the natural shape for an immutable prediction result --
    satisfy this Protocol structurally."""

    @property
    def mean(self) -> float: ...

    def cdf(self, k: int) -> float:
        """P(strikeouts <= k)."""
        ...


class StrikeoutModel(ABC):
    model_version: ClassVar[str]

    @abstractmethod
    def predict(self, features: dict[str, Any]) -> StrikeoutDistribution:
        """`features` is one row's `feature_values.features` blob (see
        features/registry.py). Must not raise for missing optional keys --
        use `.get()` with a neutral default, consistent with the rest of
        the pipeline's "visible degradation, not silent, not a crash"
        principle."""
        raise NotImplementedError
