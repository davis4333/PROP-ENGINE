# Historical Backfill — Design

Status: **implemented and complete** for the core data domains
(schedule/games, actual starters, pitcher outcomes, lineups) across the
full 2023-present window, plus **historical weather** and **computed park
factors** (Phase 4, this section updated accordingly). The
STRICT_LIVE_COMPATIBLE training-dataset builder and baseline/challenger
walk-forward evaluation are also implemented and have run against the
complete dataset. **Still not implemented**: pitch-level detail,
rest/workload features beyond `rest_days`, opponent rolling context. See
`CURRENT_STATE_AUDIT.md` for the authoritative up-to-date status and
`TRAINING_READINESS_REPORT.md` for training results.

## Why a separate subsystem, not an extension of the live pipeline

The live pipeline (`orchestration/run_slate.py`, `pit/asof.py`,
`features/`, `models/`, `decision/`) exists to answer one question
correctly: *what did Cassandra actually know before this game's first
pitch?* Its leakage gate (`pit/asof.py`'s `latest_as_of`/`all_as_of`/
`latest_grouped_as_of`) enforces that by filtering on `ingested_at` —
the real, physical wall-clock time a row was written — never a value any
adapter or backfill process could fabricate or backdate.

A historical backfill running in 2026 for a 2023 game cannot honestly
produce a row whose `ingested_at` is anything other than "2026, whenever
the backfill ran." That's correct and required (CLAUDE.md non-negotiable:
never fake or backdate `ingested_at`), but it also means a backfilled row
is *structurally* invisible to `pit/asof.py`'s gate for any cutoff before
the backfill actually ran — it can't reconstruct "what was knowable on
date X" through that mechanism at all, regardless of intent.

So this backfill writes to its own tables (`db/models/historical.py`:
`HistoricalPitcherStart`, `HistoricalLineup`, plus `BackfillRun`/
`BackfillItem` for job tracking), never to `raw_pitcher_game_logs`,
`raw_final_box_scores`, `raw_lineups`, or any other live `raw_*` table.
`pit/asof.py`, `features/builders.py`, `models/baseline.py`, and
`decision/engine.py` are verified (via an AST-based structural test,
`tests/integration/test_historical_backfill.py`) to never reference these
tables at all — not "don't currently," but "can't, the code doesn't
mention them." This is deliberate: the live point-in-time protections are
never weakened to accommodate historical data, per the backfill mission's
own non-negotiable rules.

Reconstructing "what was knowable when" for training purposes is a
**separate, explicit availability policy** (see
`HISTORICAL_AVAILABILITY_POLICY.md`), based on the real world's own
timeline (a prior game's stats become eligible once that prior game
actually reached Final) rather than `ingested_at`. That policy is
**designed but not yet implemented as code** — the training dataset
builder that would apply it doesn't exist yet.

## Data flow

```
schedule (one range call per season slice of the requested window)
    │  MLB Stats API: GET /api/v1/schedule?startDate=...&endDate=...
    │  upserts venues/teams/games (identity_resolver.py, extended with
    │  game_type/season) for EVERY game type returned -- storage is
    │  unconditional; classification into a training cohort happens later
    ▼
game IDs (mlb_game_pk, deduped)
    │
    ▼
one live-feed call per game
    │  MLB Stats API: GET /api/v1.1/game/{pk}/feed/live
    │  covers both teams' full boxscores in a single request -- pitching
    │  lines AND starting lineups together, never a separate call per
    │  pitcher or per team
    ▼
normalize
    │  actual starters (pitching.gamesStarted == 1 -- NOT the live
    │  pipeline's probablePitcher concept, which historical schedule
    │  responses don't reliably retain)
    │  full pitcher-outcome fields (K, BF, pitches, strikes/balls, hits,
    │  BB, HBP, HR, ER, R, outs, IP, decision)
    │  starting lineups (battingOrder + position)
    ▼
upsert by natural key
    (mlb_game_pk, player_mlb_id) -> historical_pitcher_starts
    (mlb_game_pk, team_mlb_id, player_mlb_id) -> historical_lineups
```

## Resumability and idempotency

Both come from `BackfillItem`: one row per unit of work, keyed by
`(domain, work_key)`, globally unique (not scoped to a single
`BackfillRun`) so a later run — resumed or fresh — sees the same row and
its real prior status regardless of which run first did the work.

- `domain="schedule"`, `work_key="{season}:{window_start}:{window_end}"`
  — keyed on the **exact requested window**, not just the season. An
  earlier narrow-window discovery (e.g. a single-day dry run) must never
  be mistaken for having covered a later, wider request for the same
  season — this was a real bug found and fixed during this build (see
  the commit history and the regression test
  `test_discover_games_for_a_new_wider_window_is_not_short_circuited_by_an_earlier_narrow_one`).
- `domain="game_feed"`, `work_key="{mlb_game_pk}"` — one row per game.
  Marked `succeeded` only after every pitcher's row has been written for
  that game; `skipped` if the game hasn't reached `Final` yet (retryable
  automatically on a later pass, not a permanent failure); `failed` after
  exhausting retries or hitting a permanent error (retryable on demand via
  `retry-backfill-failures`).

Every `BackfillItem` transition **commits immediately** (not just
flushes) — see `historical/backfill.py`'s module docstring. A
multi-thousand-game backfill can run for over an hour; relying on a
single commit at the very end would mean a process restart, redeploy, or
crash loses every already-completed item, defeating the entire point of
resumability. Verified empirically during this build: interrupting a
running backfill and rerunning the identical command resumed instantly
with zero re-fetched games and zero duplicate rows.

Duplicate prevention is structural, not a check-then-insert race: both
historical tables use `INSERT ... ON CONFLICT (natural key) DO UPDATE`,
so even a rerun that bypasses the `BackfillItem` check entirely (e.g. a
genuine correction pass) can never produce two rows for the same
`(game, player)` — the later write's values simply win.

## Conservative by design

- Sequential execution. `BackfillConfig.concurrency` exists as a plumbed-
  through parameter for a future concurrent executor, but **is not
  implemented as real concurrency in this pass** — SQLAlchemy's `Session`
  is not thread-safe, and building genuine concurrent DB writes safely
  (per-thread sessions, connection pooling tuning) is a larger change
  than this pass scopes. What actually runs today is sequential, with a
  real per-request delay (`--request-delay`, default 0.25s).
- Bounded retry with exponential backoff + jitter
  (`_request_with_retry`): `429`/`5xx` responses are retried up to
  `--max-retries` (default 5); any other `4xx` is treated as permanent
  (a `404` will never succeed no matter how many times it's retried) and
  fails immediately without wasting further calls.
- One schedule call per season slice, not per day — MLB's schedule
  endpoint supports a `startDate`/`endDate` range in a single request.
  Iterating a 3.5-year range one calendar day at a time would be well
  over a thousand avoidable calls; one range call per season is
  typically 4-5 calls total for the full 2023-present window.

## Historical weather (Phase 4, implemented)

Unlike the live pipeline (which calls Open-Meteo separately), historical
weather turned out to need no new external fetch at all: MLB's own
`feed/live` payload -- the SAME response `process_game_feed` already
fetches per game -- carries a `gameData.weather` block (`condition`,
`temp`, `wind`) and `gameData.venue.id`, ground truth for that specific
game (including dome/retractable-roof venues, which report MLB's own
condition value, e.g. `"Dome"`, as-is). The original backfill pass
discarded this field; `historical/backfill.py`'s `process_game_feed` now
captures it directly into `historical_weather_observations`
(`db/models/historical.py`'s `HistoricalWeatherObservation`) on every new
game, and a dedicated `process_weather_for_game`/`run_weather_backfill`
pass (`cassandra backfill-weather`) re-fetches the same feed URL to
enrich games backfilled before this feature existed. `features/builders.py`'s
`compute_weather_adjustment` (the exact function the live pipeline calls)
now accepts a `WeatherLike` Protocol rather than the live-only
`RawWeatherObservation` class, so `historical/dataset_builder.py` reuses
the identical adjustment logic instead of a parallel copy.

**Actual, not forecast (flagged, not silently equivalent to live).**
This is MLB's own realized/ACTUAL weather from the completed game --
strictly more accurate than the live pipeline's own weather feature
(`adapters/weather_openmeteo.py`), which is a pregame FORECAST that can
simply be wrong. Not a leakage bug (never a future game, no cutoff
violated), but a real training-vs-production information-quality gap --
every dataset row carries `weather_source: "actual"` when weather is
available (never omitted) so this is checkable, not assumed. See
`TRAINING_DATASET_SPEC.md`.

## Park factors (Phase 4, implemented)

Computed from prior completed games at each venue, not a static table --
`historical/park_factors.py`'s `ParkFactorAccumulator` walks
`historical_pitcher_starts` in chronological order (a single forward pass,
not a query per row) and reports `venue K-rate ÷ league K-rate` (clipped
to `models/baseline.py`'s `PARK_ADJ_BOUNDS`), available only once a venue
has at least `MIN_BATTERS_FACED_FOR_PARK_FACTOR` (400) batters faced in
its own STRICTLY PRIOR history -- below that, it honestly reports
unavailable rather than a noisy early estimate. Point-in-time-safe by
construction: `historical/dataset_builder.py` calls `park_factor_for()`
for a row BEFORE `record_outcome()` for that same row, so a game's own
outcome (or any later game's) can never influence its own factor --
verified by `tests/unit/test_park_factors.py` and a dedicated leakage test
in `tests/integration/test_dataset_builder.py`.

## What's still explicitly out of scope

Reported honestly here and in `audit-historical-coverage`'s output, not
silently omitted:

- Pitch-level / plate-appearance detail (velocity, pitch type, CSW rate,
  etc.) — would need a new, much larger schema (a pitch-events table) and
  careful storage-size management; deferred.
- Rest/workload and opponent rolling-context derived features — designed
  (see `HISTORICAL_AVAILABILITY_POLICY.md`), not implemented.
- Historical market lines — explicitly out of scope per the mission
  directive itself: a pitcher-strikeout **count model** trains on actual
  strikeout outcomes, not on market lines. Betting-decision evaluation
  (comparing a trained model's distribution against a market line) is a
  distinct, later concern.
