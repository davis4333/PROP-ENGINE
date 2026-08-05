# ADR 0008 — Official publication cutoff rule

**Status:** Decided and implemented (`ledger/service.py`)

## Decision

A projection is only eligible to count toward the **official public
performance record** (public Ledger aggregates, win/loss stats, etc.) if
`published_at` is before that game's official publication cutoff —
defined as the scheduled first-pitch time (`games.scheduled_start_utc`)
for this build, pending a more precise operational cutoff from Tyler
(e.g. "X minutes before first pitch" once lineups/lines are typically
locked).

Projections published after that cutoff are still recorded (nothing is
ever deleted — see the handbook's immutability principle), but:
- `projections.is_late_publication` is set `true` on the row (schema
  field added in Phase 1, see `db/models/projection.py`).
- They are excluded from official performance aggregates and from the
  headline public record, but remain visible in the full evaluated-record
  view for transparency, clearly labeled as late.

This directly prevents a failure mode the handbook's data-integrity
principle is guarding against: a late/rerun projection quietly padding
the public track record after the fact.

## Status

Implemented. `ledger/service.py`'s `publish_projection` computes and
sets `is_late_publication` on every publish (not just a schema field) —
verified by an independent architecture review. The precise cutoff still
uses `scheduled_start_utc` as this ADR names as the interim definition;
Tyler's more precise operational cutoff (e.g. "X minutes before first
pitch") remains open.
