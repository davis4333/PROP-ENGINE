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

Not yet implemented — Phase 1 (Foundation) only. Recorded as a constraint
on Phase 3's `decision/engine.py` and any related API/UI copy.
