# Strikeout Training Dataset — Spec

**Status: specification only. The builder (`cassandra build-training-
dataset`) is not implemented.** This document exists so the target shape
is settled before that code is written — see `TRAINING_READINESS_REPORT.md`
for exactly what's blocking it and `HISTORICAL_AVAILABILITY_POLICY.md`
for the eligibility rules the builder must apply.

## Unit of a row

One actual MLB starting-pitcher appearance (`historical_pitcher_starts`
where `is_starter = True` and `game_status = 'Final'`).

## Fields

### Identity

`gamePk`, `slate_date`, `scheduled_start_utc`, `pitcher_mlb_id`,
`pitcher_team`, `opponent`, `venue`, `game_type`, `pitcher_handedness`.

### Feature provenance

`dataset_version`, `feature_set_version`, `reconstruction_policy_version`,
`cutoff_timestamp`, `capture_mode`, `strict_live_compatible` (bool),
`backfill_run_id`, source coverage flags, missingness indicators — see
`HISTORICAL_AVAILABILITY_POLICY.md`'s provenance section for what each
means.

### Pregame features (target: reuse `features/expected_bf.py` and
`features/builders.py`'s existing computation logic against
availability-filtered historical inputs, not reimplement it)

expected batters faced, prior-start batters faced, recent strikeout rate,
season-to-date strikeout rate, multi-season/career strikeout rate,
rolling strikeout rates, swinging-strike rate, called-strike rate, CSW
rate, pitch-mix features, velocity features, workload, rest, role
stability, opponent rolling strikeout context, handedness matchup, park
factor, weather/historical-forecast features, lineup features (only in
`RETROSPECTIVE_ENRICHED`, per the availability policy), uncertainty/
fallback-tier indicators.

**Currently available from this backfill**: batters faced (actual, for
past starts used as history — not the target game), recent/season K-rate
history (once the schedule/outcome data this pass collects is available
across enough prior starts), rest days (derivable from `game_date`
gaps), pitcher/opponent/venue identity. **Not yet available**: pitch-mix,
velocity, CSW rate (needs pitch-level data, Phase A item 6, not
collected), park factor (needs Phase A item 8, not implemented), weather
(needs Phase A item 7, not implemented), opponent rolling strikeout
context (needs Phase A item 10, not implemented).

### Target

`actual_strikeouts`, `actual_batters_faced`, `actual_pitches`,
`actual_innings`, `game_final_status` — all directly available today from
`historical_pitcher_starts`.

## Explicitly excluded from features (any tier)

Target-game final stats, future games, end-of-season aggregates computed
using games later in that same season, future roster changes, later
corrections unavailable at the cutoff, present-day career totals when
recreating an older game.

## Freezing and versioning

Once built, a training dataset run must be immutable and versioned (same
spirit as the live projection ledger, though this is research data, not
a `raw_*`/`projections` table) — a `dataset_version` string identifying
exactly which backfill data, feature code, and availability-policy
version produced it, so a later model comparison can be attributed to a
specific, reproducible dataset rather than "whatever was in the database
at the time."
