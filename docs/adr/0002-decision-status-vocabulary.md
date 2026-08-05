# ADR 0002 — Decision vs. decision_status vocabulary

**Status:** Decided (build foundation)

## Decision

Two orthogonal fields on `projections`:

- `decision` ∈ `{OVER, UNDER, NO_PLAY}` — the directional call itself.
- `decision_status` ∈ `{QUALIFIED, UNCERTAIN, HELD, REJECTED}` — the
  confidence/gating tier the decision engine assigned.

The handbook's Appendix B example only shows a single QUALIFIED/OVER row,
so this pairing is this build's interpretation, not verified against a
second example in the spec. Flagged for Tyler's review once the decision
engine (Phase 3) is implemented and produces real NO_PLAY / UNCERTAIN
rows to look at.

## Related: evaluated / qualified / published are three distinct concepts

Per plan-approval amendment #7, these must not be conflated anywhere in
the API or UI:

1. **Evaluated** — every projection row written for a slate, regardless of
   decision or status. This is the full transparency record.
2. **Qualified** — `decision_status = 'QUALIFIED'` rows within the
   evaluated set. Still an internal/computed tier, not necessarily shown
   publicly yet.
3. **Published** — rows with a non-null `published_at` that have passed
   the publication cutoff rule (ADR 0008). This is the actual public
   record. A row can be QUALIFIED and never published (e.g. human
   approval pending, or it arrived too late — see ADR 0008).

The Today page must show the evaluated set (transparency), clearly marking
which subset is qualified and which subset is actually published. Ledger
aggregates/official performance stats are computed from **published**
rows only.
