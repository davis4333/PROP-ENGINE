# ADR 0013 — Fixture/demo slates use a real, clearly historical, completed date

**Status:** Decided (applies starting Phase 2/4 fixture work)

## Decision

Per plan-approval amendment #1: demo and test fixtures must not use a
"today"-styled or future-looking date (the original plan draft used
2026-08-04, which reads as "current/future" rather than obviously
historical). Fixture slates use a real, clearly-past MLB date where games
are unambiguously `Final`, so the graded demo is honestly historical, not
staged to look like a live/current result.

Chosen fixture date: **2023-06-15** (a real regular-season MLB date, well
in the past relative to any plausible run of this code, all games
long-since `Final`). Fixture data built against this date is still
synthetic/representative (see `CURRENT_STATE_AUDIT.md`), not scraped real
box scores, but the date itself is chosen to be unambiguously historical.

## Status

No fixtures exist yet — Phase 1 (Foundation) has no adapters beyond
static park factors and no slate concept wired up yet. This ADR fixes the
date convention for when Phase 2 (leakage test fixtures) and Phase 4
(full demo slate) are built.
