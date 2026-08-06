# Strikeout Training Dataset — Spec

**Status: implemented for the `STRICT_LIVE_COMPATIBLE` tier, with the
reduced feature set noted below** (`cassandra build-training-dataset` /
`dataset-status` / `audit-training-dataset` / `export-training-dataset`;
`engine/src/cassandra/historical/dataset_builder.py` +
`historical/availability.py`). `RETROSPECTIVE_ENRICHED` remains
unimplemented (nothing to enrich with yet — see "Not yet available"
below). See `TRAINING_READINESS_REPORT.md` for what building a dataset
does and does not unblock (a built dataset is not yet a model
evaluation), and `HISTORICAL_AVAILABILITY_POLICY.md`'s intent for the
eligibility rule the builder implements
(`availability.eligible_prior_starts`: a pitcher's own prior Final starts,
strictly before the target game's date — verified by a dedicated leakage
test suite, `engine/tests/integration/test_dataset_builder.py`).

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

**Currently emitted by the builder** (each row): `expected_bf` (+ tier,
starts-used), `recent_k_rate` (+ tier, starts-used), `rest_days`,
`prior_starts_available`, pitcher/team/opponent identity, `game_type`,
`season` — all computed only from that pitcher's own earlier Final starts
(`availability.eligible_prior_starts`), reusing
`features/expected_bf.py`/`features/builders.py`'s exact pure functions
via a small duck-typed adapter (`dataset_builder._PriorStartShim`), not a
reimplementation. **Not yet available** (see every manifest's
`excluded_feature_groups`, always populated, never silently omitted):
pitch-mix, velocity, CSW rate (needs pitch-level data, Phase A item 6,
not collected), park factor (Phase A item 8, not implemented), weather
(Phase A item 7, not implemented), opponent rolling strikeout context
(Phase A item 10, not implemented), lineup features, umpire,
pitcher handedness (identity resolution for historical players hasn't
run in this pass — see `CURRENT_STATE_AUDIT.md`).

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

Each build writes a gzipped JSONL data file plus a JSON manifest under
`engine/data/training_datasets/` (gitignored — a regeneratable research
artifact, not source; see `dataset_builder.py`'s module docstring for why
this is a file pair rather than a new Postgres table), keyed by a fresh
`dataset_id` per build — nothing in the codebase ever reopens an existing
dataset file for writing, which is what gives it its practical
immutability. The manifest records `dataset_version` (builder version +
availability-policy version), `feature_set_version`,
`expected_bf_version`, `seasons`, `game_types`, `row_count`, and
`excluded_feature_groups`, so a later model comparison can be attributed
to a specific, reproducible dataset rather than "whatever was in the
database at the time."
