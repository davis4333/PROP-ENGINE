# ADR 0014 — The Odds API is the live line source, not Underdog

**Status:** Decided (real vendor substituted for the unresolved Underdog
decision; not a resolution of that decision)

## Decision

`adapters/lines_odds_api.py` (`LinesOddsApiAdapter`) is a real, paid,
licensed integration with [The Odds API](https://the-odds-api.com),
aggregating regulated US sportsbooks (FanDuel, DraftKings, Bovada,
etc.). When `ODDS_API_KEY` is configured,
`orchestration/run_slate.py`'s `_ingest_lines()` uses it in place of
`adapters/lines_manual.py`'s drop-folder stand-in — never alongside it,
specifically to avoid two disagreeing sources tripping
`ingestion/quality_gate.py`'s `check_line_conflict` DATA_CONFLICT
finding on the same pitcher/game/market.

## Why this needed its own ADR

The handbook and `docs/DECISION_LEDGER.csv` are explicit: Underdog is
the intended first public line source, and Underdog's real
data-acquisition method/ToS is legally **unresolved** — CLAUDE.md's
non-negotiables rule out scraping it or hitting its internal
(undocumented, unauthorized) app API, which was explicitly proposed and
declined during this build. That decision stands unchanged.

But this adapter is now the vendor actually powering real, live,
publicly-visible projections on a production deployment, spending real
subscription/API-credit money — a decision weighty enough that every
comparable one elsewhere in this repo (ADR 0006, ADR 0011) got a
numbered ADR, not just prose in `CURRENT_STATE_AUDIT.md` and commit
messages. This ADR exists to close that documentation gap, flagged by an
independent architecture review.

## What this is *not*

- **Not Underdog.** The Odds API has no relationship with Underdog and
  does not carry Underdog's DFS pick'em lines. These are real
  sportsbook point-total lines (e.g. "Over/Under 5.5 strikeouts,
  -110/-110"), a different, legitimate, but distinct market. Nothing in
  `decision/engine.py` treats these prices as an implied probability
  (ADR 0006 still holds) — only the `line` (point total) is consumed;
  `over_price`/`under_price` are stored but never read by the decision
  gate.
- **Not a resolution of the Underdog decision.** `docs/DECISION_LEDGER.csv`'s
  "Primary book/feed" row should be read alongside this ADR: Underdog is
  still the confirmed intended source; this is the interim real-data
  seam it was built to accept, not a replacement decision.

## Known limitations, honestly

- Free tier is 500 requests/month, easily exceeded by a daily
  automated scheduler across a full MLB slate — a real operating cost
  to budget for (see `CURRENT_STATE_AUDIT.md`).
- Bookmaker selection prefers DraftKings, falling back to whichever
  other book has posted the market first; no cross-book consensus.
- Vendor player names are matched by exact string against that slate's
  confirmed starters; a same-name collision is detected and the line is
  dropped with a warning rather than guessed at (see the adapter's own
  docstring and its regression tests).

## Revisit when

A real Underdog partnership/API access is confirmed, or a different
licensed vendor is chosen for cost/coverage reasons — the adapter
contract (`adapters/base.py`) makes either a swap of this one file, not
a pipeline change.
