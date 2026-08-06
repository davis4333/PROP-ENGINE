# Historical Backfill — Data Dictionary

Covers the tables actually implemented in this pass
(`engine/src/cassandra/db/models/historical.py`). See
`HISTORICAL_BACKFILL_DESIGN.md` for why these are separate from the live
`raw_*` tables.

## `backfill_runs`

One row per invocation (or resumed continuation) of `backfill-mlb`.

| Column | Type | Notes |
|---|---|---|
| `backfill_run_id` | string PK | `backfill_{12 hex chars}` |
| `requested_start_date` / `requested_end_date` | date | The range asked for on the command line |
| `status` | string | `running` \| `completed` \| `failed` \| `paused` \| `cancelled` |
| `source` | string | Always `mlb_stats_api_historical_backfill` today |
| `domain` | string | `mlb_core` for a real run; `test` only appears in test-suite scratch rows |
| `season` | int, nullable | Not currently populated per-run (a run can span multiple seasons); reserved |
| `current_cursor` | string, nullable | Live progress marker, e.g. `season:2024:schedule` or `game:717753` — what `backfill-status` shows mid-run |
| `total_work_items` / `completed_work_items` / `failed_work_items` / `skipped_work_items` | int | Progress counters, updated after every item |
| `retry_count` | int | Incremented once per `retry-backfill-failures` invocation against this run |
| `started_at` / `finished_at` / `last_success_at` | timestamptz | |
| `last_error` | string, nullable | Most recent failure's short description |
| `code_commit_sha` | string, nullable | Best-effort `git rev-parse HEAD` at run start; provenance only, never load-bearing |
| `adapter_version` | string | `historical/backfill.py`'s `BACKFILL_ADAPTER_VERSION` |
| `config` | jsonb | The resolved `BackfillConfig` used (concurrency, delay, retries, game_types, dry_run) |
| `coverage_summary` | jsonb, nullable | Only populated for a `--dry-run` invocation today |

## `backfill_items`

One row per unit of resumable/idempotent work. Unique on `(domain,
work_key)` — **globally**, not scoped to one run, which is what makes
resumption across separate CLI invocations correct.

| Column | Type | Notes |
|---|---|---|
| `backfill_item_id` | UUID PK | |
| `backfill_run_id` | string, FK | The run that most recently touched this item (not necessarily the one that created it) |
| `domain` | string | `schedule` \| `game_feed` |
| `work_key` | string | `schedule`: `"{season}:{window_start}:{window_end}"`. `game_feed`: the `mlb_game_pk` as a string. |
| `status` | string | `pending` \| `in_progress` \| `succeeded` \| `failed` \| `skipped` |
| `attempts` | int | Incremented every time this item is finalized (success, failure, or skip) |
| `last_error` | string, nullable | |
| `last_attempted_at` / `completed_at` | timestamptz, nullable | |

## `historical_pitcher_starts`

One row per pitcher appearance in one historical game (starters *and*
relievers — `is_starter` distinguishes them). Unique on `(mlb_game_pk,
player_mlb_id)`; upserted, not append-only (see the design doc for why
that's the correct, safe idempotency mechanism here, distinct from the
live `raw_*` tables' immutability discipline).

| Column | Type | Notes |
|---|---|---|
| `mlb_game_pk` | int | |
| `game_date` | date | MLB's `officialDate` for the game |
| `player_mlb_id` | int | |
| `team_mlb_id` / `opponent_mlb_id` | int, nullable | |
| `is_starter` | bool | `True` iff MLB's own boxscore reports `pitching.gamesStarted == 1` for this pitcher in this game |
| `pregame_starter_confirmation_captured` | bool | **Always `False`** for backfilled rows. An actual historical starter identified after the fact from the box score is explicitly *not* the same claim as a live pregame-confirmed probable pitcher (`raw_probable_pitchers.is_confirmed`) — this column makes that distinction queryable rather than letting it get silently conflated downstream. |
| `batters_faced`, `strikeouts`, `pitches_thrown`, `strikes`, `balls`, `hits_allowed`, `walks`, `hit_batters`, `home_runs_allowed`, `earned_runs`, `runs_allowed`, `outs_recorded`, `innings_pitched` | numeric, nullable | Directly from MLB's boxscore `pitching` stat block |
| `decision` | string, nullable | MLB's raw `note` field, e.g. `"(W, 3-1)"` — stored as-is, not parsed into a separate W/L/S/H/BS code |
| `game_status` | string | The game's `abstractGameState` at fetch time — always `Final` for a row that reached `succeeded`, since `process_game_feed` skips (doesn't write) non-Final games |
| `capture_mode` | string | Always `HISTORICAL_RECONSTRUCTED` for rows this backfill writes |
| `source_id` | string, FK | `mlb_stats_api_historical_backfill` |
| `backfill_run_id` | string, FK, nullable | |
| `observed_at` | timestamptz | The backfill's own fetch time (`fetched_at`) — **not** derived from the game's real date; see the availability policy doc for how eligibility is actually determined for training |
| `ingested_at` | timestamptz | Real physical write time, server-default `now()` — never backdated |
| `payload` | jsonb | `{"person": ..., "pitching": ...}` — enough to reproduce the normalization, not the entire game feed (storage-conscious) |
| `record_hash` | string, nullable | Reserved, not currently populated |

## `historical_lineups`

One row per batter's slot in one team's actual (post-hoc, box-score-
derived) starting lineup. Unique on `(mlb_game_pk, team_mlb_id,
player_mlb_id)`.

| Column | Type | Notes |
|---|---|---|
| `mlb_game_pk`, `game_date`, `team_mlb_id`, `player_mlb_id` | | |
| `batting_order` | string, nullable | MLB's raw 3-digit code, e.g. `"100"` (leadoff), `"200"`, ... |
| `position` | string, nullable | Abbreviation, e.g. `"CF"` |
| `capture_mode` | string | Always `HISTORICAL_ACTUAL` — this is the game's real, final lineup, not a pregame-known one. There is no trustworthy pregame-availability timestamp for this in the free MLB Stats API, so a strict live-compatible training feature set must exclude it (see the availability policy doc) unless that changes. |
| `source_id`, `backfill_run_id`, `observed_at`, `ingested_at`, `payload` | | Same meaning as above |

## `historical_weather_observations` (Phase 4)

One row per game's actual observed weather. Unique on `mlb_game_pk`.
Sourced from the same `feed/live` payload `historical_pitcher_starts`/
`historical_lineups` are built from (`gameData.weather`/`gameData.venue`)
-- ground truth for that specific game, not a nearby-station archive
approximation. Dome/retractable-roof venues report MLB's own `condition`
value as-is (e.g. `"Dome"`, `"Roof Closed"`).

| Column | Type | Notes |
|---|---|---|
| `mlb_game_pk`, `game_date` | | |
| `venue_mlb_id` | int, nullable | Raw MLB venue id from `gameData.venue.id` |
| `condition` | string, nullable | MLB's free-text condition, e.g. `"Partly Cloudy"`, `"Dome"` |
| `temp_f` | numeric, nullable | Parsed from `gameData.weather.temp` |
| `wind_mph` | numeric, nullable | Parsed from the leading number in `gameData.weather.wind` |
| `wind_detail` | string, nullable | The direction/description portion of `gameData.weather.wind` (e.g. `"R To L"`) |
| `capture_mode` | string | Always `HISTORICAL_ACTUAL` |
| `source_id`, `backfill_run_id`, `observed_at`, `ingested_at`, `payload` | | Same meaning as above |

## `games` (existing table, two columns added this pass)

| Column | Type | Notes |
|---|---|---|
| `game_type` | string, nullable | MLB's own schedule `gameType` code. Observed values in this backfill: `R` (regular season), `S` (spring training), `E` (exhibition), `A` (all-star). Postseason is **not** a single code — MLB splits it into `F` (wild card), `D` (division series), `L` (league championship series), `W` (World Series); all four should be treated as postseason by any consumer. |
| `season` | int, nullable | MLB's own `season` field, as an integer |
