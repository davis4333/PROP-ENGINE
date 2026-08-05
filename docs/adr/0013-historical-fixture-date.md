# ADR 0013 — Fixture/demo slates use a real, clearly historical, completed date

**Status:** Decided and implemented

## Decision

Per plan-approval amendment #1: demo and test fixtures must not use a
"today"-styled or future-looking date (the original plan draft used
2026-08-04, which reads as "current/future" rather than obviously
historical). Fixture slates use a real, clearly-past MLB date where games
are unambiguously `Final`, so the graded demo is honestly historical, not
staged to look like a live/current result.

Chosen fixture date: **2023-06-15** (a real regular-season MLB date, well
in the past relative to any plausible run of this code, all games
long-since `Final`).

## Status

Implemented, and more thoroughly than originally planned: fixture data
for this date is real captured MLB Stats API responses (not synthetic),
replayed via `scripts/seed_demo_slate.py` against a real Postgres
database (see `CURRENT_STATE_AUDIT.md`'s "Fixture demo slate" section) —
verified by an independent architecture review. The demo slate's 4-line
manual drop file was hand-picked so the real recorded outcomes produce a
WIN, a LOSS, and a PUSH, honestly, not staged.
