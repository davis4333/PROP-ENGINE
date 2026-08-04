# ADR 0001 — Point-in-time cutoff semantics

**Status:** Decided (build foundation)

## Decision

Every raw ingestion table carries two timestamps:
- `observed_at` — the source's claimed effective/as-of time for the fact.
- `ingested_at` — the time this system physically wrote the row (server clock).

An as-of query for cutoff `T` requires **both** `ingested_at <= T` and
`observed_at <= T`, and among matches takes the latest by
`(observed_at, ingested_at)`.

`ingested_at` is the true leakage gate — it is when the system could
actually have known the fact, regardless of what a source claims about its
own effective time. `observed_at` is a second, independent filter that
protects against a source backdating or misreporting its effective time in
a way that would let a fact leak in early if we only trusted our own clock.
Requiring both to hold is stricter (and safer) than either alone.

## Consequence

`raw_final_box_scores` is never read through this path at all — it is
structurally excluded from `features/` and `models/` code, and only
`grading/` may query it, gated additionally on `game_status == 'Final'`.
This is a second, independent safeguard against outcome leakage beyond the
timestamp filter.

All timestamp columns are `timestamptz` (stored UTC). See ADR 0009 for the
UTC/slate-date convention.
