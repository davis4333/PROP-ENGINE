# ADR 0003 — Model interface must support more than Poisson

**Status:** Decided and implemented (`models/interface.py`, `models/baseline.py`)

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

Implemented. `models/interface.py` defines `StrikeoutModel`/
`StrikeoutDistribution` per the sketch above; `models/baseline.py`
implements `k-model-0.1.0` (Poisson) against it; `decision/engine.py`
only ever calls the interface, never a concrete distribution family —
verified by an independent architecture review. This ADR's constraint
held; no negative-binomial/simulation-based model exists yet, but
nothing downstream would need to change to add one.
