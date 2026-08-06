# ADR 0008 — Official publication cutoff rule

**Status:** Decided and implemented (`ledger/service.py`)

## Decision

A projection is only eligible to count toward the **official public
performance record** (public Ledger aggregates, win/loss stats, etc.) if
`published_at` is before that game's official publication cutoff —
defined as `settings.publication_freeze_minutes_before_first_pitch`
(default 15) minutes before the scheduled first-pitch time
(`games.scheduled_start_utc`), **not** the literal first-pitch moment.
15 is the mission directive's own suggested working default —
configurable via env var, still not a Tyler-confirmed operational
number, same provisional status `decision_edge_threshold` has (see the
comment next to both settings in `config.py`). The point of a freeze
window rather than "before literal first pitch" is a pick an operator
can actually act on before it locks, not one that could still change up
to the last minute.

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
verified by an independent architecture review, and by a dedicated
test (`test_publication_inside_the_freeze_window_is_late_even_though_
before_first_pitch`) proving a publication landing inside the freeze
window is correctly marked late even though it's still genuinely before
first pitch. The precise freeze-window length (15 minutes) is a
configurable default, not a business-approved number — Tyler's real
operational cutoff remains open; changing it is a one-line config
change (`PUBLICATION_FREEZE_MINUTES_BEFORE_FIRST_PITCH` env var), not a
code change.
