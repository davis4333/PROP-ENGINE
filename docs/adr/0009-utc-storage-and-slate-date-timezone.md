# ADR 0009 — UTC storage, operating timezone for slate-date

**Status:** Decided (build foundation)

## Decision

- All timestamp columns are `timestamptz`, and the application always
  writes/reads them in UTC. No naive datetimes anywhere in `db/models/`.
- `slate_date` (used by `snapshots`, `pipeline_runs`, and CLI/API
  `?slate_date=` params) is a calendar date, not a timestamp. It is
  derived by converting a game's `scheduled_start_utc` into the
  **operating timezone** (`OPERATING_TIMEZONE`, default
  `America/New_York` — configured in `config.py` / `.env.example`, since
  MLB slates and Underdog's own day-boundaries are conventionally
  US-Eastern) and taking that local calendar date. A single UTC day can
  span parts of two slate-dates and vice versa; this conversion is the
  single source of truth for "which slate does this game belong to," and
  must live in one function (`config.slate_date_for(scheduled_start_utc)`)
  rather than being re-derived ad hoc in multiple places.
- Display timezone (what the frontend shows to a viewer) is a separate,
  purely presentational concern — the API always returns UTC
  ISO-8601 timestamps; the Next.js frontend (Phase 4) converts to local
  display time client-side. The API never bakes a display timezone into
  its responses.

## Status

`config.py`'s `OPERATING_TIMEZONE` setting and `slate_date_for()` helper
are built in Phase 1. Nothing in Phase 1 yet computes a real slate_date
from live data (no schedule adapter exists yet), but the DB schema and
config are already timezone-correct so this doesn't need revisiting later.
