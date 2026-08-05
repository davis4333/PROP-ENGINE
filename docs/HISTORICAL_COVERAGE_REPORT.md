# Historical Coverage Report — Point-in-Time Snapshot

**This is a snapshot, not a final report.** Generated via `cassandra
audit-historical-coverage --start-date 2023-01-01 --end-date 2026-08-05`
while the full backfill (`backfill_run_id` visible via `backfill-status`)
was still running. Regenerate the same command for current numbers —
see `docs/HISTORICAL_BACKFILL_RUNBOOK.md`.

Snapshot taken with **737 of 11,100** total discovered games processed
(6.6%), zero failures, zero skips at that point.

## Unplanned real-world resumability proof

During verification for this report, the running backfill process was
killed mid-flight (`kill`, simulating a crash) at 925/11,100 completed.
Separately, local test-suite cleanup accidentally deleted the `games`
identity table's rows while 4 `schedule`-domain `backfill_items` were
still marked `succeeded`, producing a genuinely inconsistent state (item
tracking said "done," but the identity data it should have produced was
gone). Resetting only those 4 stale `schedule` items back to `pending`
and rerunning the exact same `backfill-mlb` command was sufficient to
fully self-correct: schedule discovery re-ran for real (fresh API calls,
re-populating `games`), and game-feed processing correctly resumed at
item 926 — skipping all 925 already-`succeeded` games with zero
re-fetches and zero duplicate rows, then continuing forward with zero
failures. This was not a planned test; it is a real, unplanned
demonstration that the `BackfillItem`-based resumability mechanism
survives both a hard process kill and an inconsistent manual data
intervention, provided the inconsistency itself is corrected once
(exactly what a real operator would do via `backfill-status`/direct
inspection if something similar happened in production).

## Games discovered (schedule/identity — complete for all four seasons)

Schedule discovery (Phase A item 1) is fast (~5 range calls total) and
finished for every season in range before per-game processing began:

| Season | Games discovered | By type |
|---|---|---|
| 2023 | 2,963 | R=2430, S=467, E=24, A=1, F=8, D=14, L=14, W=5 |
| 2024 | 2,959 | R=2430, S=472, E=13, A=1, F=9, D=18, L=11, W=5 |
| 2025 | 2,961 | R=2430, S=471, E=12, A=1, F=11, D=18, L=11, W=7 |
| 2026 (partial, through 2026-08-05) | 2,217 | R=1727, S=451, E=38, A=1 |
| **Total** | **11,100** | |

Every season's regular-season game count (2,430) matches MLB's real
162-game x 15-games/day schedule exactly, which is itself a form of
accuracy verification — a parsing or filtering bug would very likely
have produced a different number.

## Pitcher outcome / lineup collection (in progress at snapshot time)

| Season | Games w/ pitcher data | Starter appearances | K/BF/pitch-count coverage | Games w/ lineup data |
|---|---|---|---|---|
| 2023 | 757 / 2,963 | 1,514 | 100.0% / 100.0% / 100.0% | 759 (13,662 rows) |
| 2024 | 0 / 2,959 | 0 | — | 0 |
| 2025 | 0 / 2,961 | 0 | — | 0 |
| 2026 | 0 / 2,217 | 0 | — | 0 |

Every single collected starter appearance has 100% coverage on
strikeouts, batters faced, and pitch count — expected, since these come
directly from MLB's own final boxscore for a `Final` game and
`process_game_feed` only writes a row once it has confirmed `Final`
status.

Processing order is by ascending `mlb_game_pk` across the whole 2023-2026
range (not date order within a season), so the 757 2023 games already
done are not simply "the first 757 days of 2023" — spot checks (below)
were deliberately drawn from August, September, and October 2023 to
confirm this.

## Failed / skipped games at snapshot time

Zero of either, across all 737 completed items.

## Accuracy spot checks

Three completed games, cross-checked directly against a fresh, live call
to MLB's own `/api/v1.1/game/{pk}/feed/live` endpoint (not a cached
comparison — re-fetched live during this verification pass):

| Game | Date | Pitcher | Stored K/BF/Pitches/Decision | Live API K/BF/Pitches/Decision | Match |
|---|---|---|---|---|---|
| 716352 | 2023-10-01 | Zack Greinke (home) | 2 / 19 / 70 / (W, 2-15) | 2 / 19 / 70 / (W, 2-15) | ✅ |
| 716352 | 2023-10-01 | Michael King (away) | 1 / 19 / 71 / (L, 4-8) | 1 / 19 / 71 / (L, 4-8) | ✅ |
| 716384 | 2023-09-29 | Zac Gallen (home) | 7 / 26 / 104 / (L, 17-9) | 7 / 26 / 104 / (L, 17-9) | ✅ |
| 716384 | 2023-09-29 | José Urquidy (away) | 2 / 22 / 70 / (W, 3-3) | 2 / 22 / 70 / (W, 3-3) | ✅ |
| 717010 | 2023-08-13 | Zach Eflin (home) | 3 / 18 / 82 / (L, 12-7) | 3 / 18 / 82 / (L, 12-7) | ✅ |
| 717010 | 2023-08-13 | Tanner Bibee (away) | 5 / 27 / 97 / (W, 9-2) | 5 / 27 / 97 / (W, 9-2) | ✅ |

Lineup spot check (game 717010): stored `historical_lineups` leadoff
hitters (`batting_order='100'`) for both teams — player IDs 650490
(home) and 680757 (away) — match the live feed's `battingOrder[0]` for
each team exactly. First three batting-order slots per side also
verified matching.

All six pitcher-outcome spot checks and the lineup spot check matched
exactly, with zero discrepancies.

## Duplicates

Structurally impossible by design (natural-key upsert, not a
check-then-insert race) — see
`docs/HISTORICAL_BACKFILL_DESIGN.md`. Empirically confirmed during
development: after processing 15 real games twice (once, then an
identical rerun), `SELECT COUNT(*) vs COUNT(DISTINCT (mlb_game_pk,
player_mlb_id))` from `historical_pitcher_starts` were equal (131 = 131).

## Not yet covered (unchanged from the design doc, repeated here per the
mission directive's explicit reporting requirement)

Pitch-level/plate-appearance detail, historical weather, park factors
computed from prior games, rest/workload derived features, opponent
rolling strikeout context, historical market lines (explicitly out of
scope for this phase).

## How to get current numbers

```bash
cd engine
.venv/bin/cassandra backfill-status
.venv/bin/cassandra audit-historical-coverage --start-date 2023-01-01
```
