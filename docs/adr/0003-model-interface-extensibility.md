# ADR 0003 — Model interface must support more than Poisson

**Status:** Decided (design constraint for Phase 3, not yet implemented)

## Decision

`k-model-0.1.0` (Phase 3) implements a Poisson baseline, but
`models/interface.py` must define an abstract contract that does not bake
in the Poisson assumption, so negative binomial (handles overdispersion),
Monte Carlo simulation, and later trained/ML models can be swapped in
without touching the decision engine or ledger writer.

Sketch of the contract (to be implemented in Phase 3):

```python
class StrikeoutModel(ABC):
    model_version: str

    @abstractmethod
    def predict(self, features: FeatureRow) -> StrikeoutDistribution: ...

class StrikeoutDistribution(Protocol):
    mean: float
    def cdf(self, k: int) -> float: ...   # P(strikeouts <= k)
    def sample(self, n: int) -> np.ndarray: ...  # for simulation-based models
```

The decision engine only ever calls `.cdf()` / `.mean`, never assumes a
specific distributional family. `k-model-0.1.0`'s Poisson implementation
and a documented, independently versioned expected-batters-faced
calculation (ADR 0004) are the first concrete implementation, not the only
one this interface will ever support.

## Status

Not yet implemented — this is Phase 1 (Foundation) only. Recorded now so
the Phase 3 implementation doesn't accidentally hardcode Poisson into
`decision/engine.py` or the ledger schema.
