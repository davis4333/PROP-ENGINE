# Historical Backfill — Runbook

## Prerequisites

- Migrations applied: `make migrate-check` (or, from `engine/`,
  `.venv/bin/python -m alembic upgrade head`). Adds `backfill_runs`,
  `backfill_items`, `historical_pitcher_starts`, `historical_lineups`,
  and `games.game_type`/`games.season`.
- No API key needed — the MLB Stats API is free and public.
- No paid quota to manage (unlike `ODDS_API_KEY`/The Odds API) — this
  backfill only ever calls MLB's own schedule and game-feed endpoints.

## Start a backfill

```bash
cd engine
.venv/bin/python -m cassandra.cli.main backfill-mlb \
  --start-date 2023-01-01 --end-date 2026-08-05
```

Omit `--end-date` to default to "today" in `America/New_York`. Omit
`--start-date` to default to `2023-01-01`. `--season 2024` is a shortcut
for `--start-date 2024-01-01 --end-date 2024-12-31` (clipped to today).

## Resume after an interruption

Rerun the **exact same command** (same `--start-date`/`--end-date`).
`--resume` is on by default: it finds the latest matching
`BackfillRun` still in `running`/`failed`/`paused` state and continues
it. Every already-`succeeded` game is skipped without a network call —
verified empirically during this build: a rerun of an already-completed
15-game window finished in ~1 second instead of ~10, with zero new HTTP
requests and zero duplicate rows.

This works after: `Ctrl-C`, a process crash, a Replit restart, a
redeploy, or a rate-limit/timeout failure partway through a single game
— resumability is per-game (and per schedule-discovery window), not
per-run.

Pass `--no-resume` to force a brand-new `BackfillRun` row instead
(idempotency at the data level is unaffected either way — an
already-succeeded game is still skipped, just attributed to a new run
row).

## Check progress

```bash
.venv/bin/python -m cassandra.cli.main backfill-status
# or, for a specific run:
.venv/bin/python -m cassandra.cli.main backfill-status --run-id backfill_xxxxxxxxxxxx
# machine-readable:
.venv/bin/python -m cassandra.cli.main backfill-status --json
```

Shows `status`, `current_cursor` (e.g. `season:2024:schedule` or
`game:717753` — exactly where the run is right now), and the
total/completed/failed/skipped counters.

## Retry failures

```bash
.venv/bin/python -m cassandra.cli.main retry-backfill-failures --run-id backfill_xxxxxxxxxxxx
```

Re-attempts every `game_feed` item currently marked `failed` under that
run. Does **not** touch items marked `skipped` (a game that simply
hasn't reached `Final` yet) — those resolve automatically the next time
`backfill-mlb` walks the same date range, once the game has actually
finished.

## Audit coverage

```bash
.venv/bin/python -m cassandra.cli.main audit-historical-coverage \
  --start-date 2023-01-01 --end-date 2026-08-05
# or --json for machine-readable output
```

Reports, per season: games discovered (by type), games `Final`, games
with pitcher data collected, starter appearances collected (and what
fraction have strikeout/batters-faced/pitch-count data), reliever
appearances collected, lineup coverage, plus failed/skipped game lists.
Also explicitly lists what this backfill pass does **not** cover
(pitch-level detail, weather, park factors, etc.) — see
`HISTORICAL_COVERAGE_REPORT.md` for a point-in-time snapshot of this
output.

## Cancel safely

`Ctrl-C` (or `kill` the process/container). Because every item commits
immediately (not just at the end of the run), nothing already completed
is lost — the run's `status` stays `running` in the database (it never
gets a chance to update to `completed`/`failed`), which is exactly what
`--resume`'s matching logic looks for. Just rerun the same command.

## Build the training dataset

**Not yet implemented.** `cassandra build-training-dataset` does not
exist yet — see `TRAINING_DATASET_SPEC.md` and
`TRAINING_READINESS_REPORT.md` for what's designed versus built.

## Where data is stored

Postgres, in the tables described in `HISTORICAL_DATA_DICTIONARY.md` —
no separate object storage or filesystem archive is used in this pass
(the design doc's storage-conscious guidance — normalized fields in
Postgres, not full raw feed payloads — kept per-row storage small enough
that this wasn't needed; each `historical_pitcher_starts.payload` is
just the `person` + `pitching` sub-objects, not the multi-megabyte full
game feed).

## Expected storage and API-call volume

For the full 2023-01-01-to-present range (~11,100 games discovered
across all game types, confirmed by a real dry run during this build):

- **API calls**: ~5 schedule range calls (one per season slice) + 1 call
  per game (~11,100) = ~11,105 total, spread out at the configured
  request delay (default 0.25s/call) plus real network latency — full
  range takes on the order of 60-90 minutes end to end. All against
  MLB's free, unmetered Stats API — no quota to budget, unlike the live
  pipeline's Odds API integration.
- **Storage**: each `historical_pitcher_starts` row is a few hundred
  bytes of normalized columns plus a small JSONB payload (the pitcher's
  own stat block, not the full feed) — roughly 15-20 pitcher rows and
  ~18 lineup rows per game. At ~11,100 games that's on the order of
  200,000 pitcher rows and 200,000 lineup rows total; well within a
  standard managed Postgres instance's free/starter tier.

## Running on Replit

Run as a **one-off CLI invocation** via the Replit shell (or a Repl
"Run" configured for it), **not** through the in-process scheduler
(`orchestration/scheduler.py`) — that scheduler drives the live daily
pipeline (`run_slate`/`grade_slate_run`) on its own cadence and must not
be duplicated or blocked by a long-running backfill. This backfill is a
separate, resumable process by design specifically so it can be started,
interrupted (a Repl going to sleep, a redeploy), and resumed without
coordinating with the live scheduler at all — they touch entirely
disjoint tables. Do not run more than one `backfill-mlb` process
concurrently against the same database; each is sequential and
`BackfillItem`-idempotent, but two processes racing on the *same*
in-flight item could double up in-flight work needlessly (not a
correctness risk given the natural-key upsert, just a wasted-effort one).

## Running locally

Identical commands, against `DATABASE_URL` pointed at a local/dev
Postgres instance with migrations applied. See `docs/DEVELOPMENT.md` for
general local setup (`make install`, `make db-up`).

## Distinguishing live from historical records

- Live: `raw_pitcher_game_logs`, `raw_final_box_scores`,
  `raw_lineups`, and every other `raw_*` table — always written by the
  live pipeline via `ingestion/ingest_service.py`, never by this
  backfill.
- Historical: `historical_pitcher_starts`, `historical_lineups` —
  always written by this backfill, never by the live pipeline. Every row
  carries `capture_mode` (`HISTORICAL_RECONSTRUCTED` or
  `HISTORICAL_ACTUAL`) making the distinction explicit and queryable, not
  just structural.
