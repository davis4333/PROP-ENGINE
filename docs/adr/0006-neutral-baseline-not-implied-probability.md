# ADR 0006 — 0.5 is a neutral decision baseline, not an "Underdog-implied probability"

**Status:** Decided

## Decision

The decision gate (ADR 0005) compares the model's `probability_over`
against **0.5**, described strictly as a neutral baseline for measuring
edge — never described as, derived from, or presented as an
"Underdog-implied probability." Underdog's actual payout structure,
juice/vig, and contest-format-specific break-even math are explicitly
unresolved per the handbook, and this build does not invent or approximate
them.

This distinction matters beyond wording: if `probability_over: 0.5` is
ever documented as "what Underdog implies," a future reader could
reasonably treat the decision gate as payout-aware when it isn't. All
code comments, API field descriptions, and UI copy referring to this
baseline must call it a "neutral baseline" or "provisional decision
baseline," never "implied probability."

## Status

Implemented. `decision/engine.py` computes `edge_over = probability_over
- 0.5` exactly as specified, and the neutral-baseline wording rule holds
across code comments, API field descriptions, and UI copy — verified by
an independent architecture review.
