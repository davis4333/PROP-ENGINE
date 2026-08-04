# ADR 0005 — Decision edge threshold is a provisional constant

**Status:** Decided (placeholder, needs owner sign-off before real publication)

## Decision

The decision gate (Phase 3) compares model probability against a **neutral
0.5 baseline**, not any Underdog-specific implied probability — see ADR
0006. `edge = probability_over - 0.5` (or the symmetric under case), and a
projection qualifies only if `abs(edge) >= DECISION_EDGE_THRESHOLD`.

`DECISION_EDGE_THRESHOLD` (env var, default `0.05` in `.env.example`) is
an **arbitrary placeholder**, not a calibrated or business-approved value.
The handbook explicitly leaves payout-specific decision math unresolved;
this build does not invent that math, it only needs *some* number to make
the gate mechanically testable. Every place this constant is used must be
clearly commented as provisional, and `CURRENT_STATE_AUDIT.md` must list
it as an open item requiring Tyler's real threshold/calibration decision
before any projection is treated as a live public recommendation.

## Status

Not yet implemented — Phase 1 (Foundation) only.
