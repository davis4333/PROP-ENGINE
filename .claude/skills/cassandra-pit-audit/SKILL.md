---
name: cassandra-pit-audit
description: Audit a code change for point-in-time (future-data) leakage risk before it merges. Use when reviewing or writing code that queries any raw_* table, builds or reads snapshots, computes features, calls the decision engine, or touches anything upstream of ledger writes — including PR review requests, "check this for leakage," or "is this query safe." Walks the ADR 0001 cutoff checklist, the raw_final_box_scores isolation rule, and the engine/tests/pit/ suite.
---

# Cassandra point-in-time leakage audit

Future-data leakage is a release blocker (`CLAUDE.md` non-negotiable #2). This
skill is the concrete checklist for auditing any change that reads
point-in-time data. It does not fix code — see `cassandra-ledger-integrity`
and the `point-in-time-auditor` subagent for the adversarial, read-only
version of this same checklist.

## Step 1 — Identify every raw_* read the change touches

Grep the diff for references to any table in
`engine/src/cassandra/db/models/raw.py`:
`raw_schedule_events`, `raw_probable_pitchers`, `raw_lineups`,
`raw_pitcher_game_logs`, `raw_weather_observations`, `raw_park_factors`,
`raw_umpire_assignments`, `raw_lines`, `raw_final_box_scores`.

Also check anything that calls into `pit/asof.py`'s `latest_as_of()` or
builds a snapshot (`pit/snapshot_builder.py`, `snapshots` /
`snapshot_raw_refs` rows) — leakage bugs hide as much in the snapshot
freeze logic as in ad hoc queries.

## Step 2 — For each read, verify the ADR 0001 cutoff contract

Per `docs/adr/0001-point-in-time-cutoff-semantics.md`, an as-of query for
cutoff `T` must:

1. Filter `ingested_at <= T` **and** `observed_at <= T` — both, not either.
   `ingested_at` is the true leakage gate (when the system could physically
   have known the fact); `observed_at` is an independent second filter
   against a source backdating its own effective time. A query that checks
   only one is a leakage bug even if it "looks" conservative.
2. Among rows passing both filters, select the latest by
   `(observed_at, ingested_at)` — not just `ingested_at`, and not
   `created_at`/`id` order.
3. Never accept a cutoff that isn't explicitly passed in — no query may
   default to `NOW()` in engine/model/feature code (only ingestion adapters
   observing live data should ever touch wall-clock time).

Reject a query that computes "latest row" from a raw table without both
predicates, even if the surrounding code looks careful — this is exactly
the class of bug the two-timestamp design exists to catch.

## Step 3 — Verify raw_final_box_scores isolation

Per ADR 0001's consequence and `raw.py`'s module docstring:
`raw_final_box_scores` must **never** be read from `pit/asof.py`,
`features/`, or `models/` — only `grading/` may query it, and only rows
with `game_status == 'Final'`.

- `grep -rn "raw_final_box_scores\|RawFinalBoxScore" engine/src/cassandra/`
  and confirm every hit outside `engine/src/cassandra/grading/` is either a
  migration, the model definition itself (`db/models/raw.py`), or a test —
  never `pit/`, `features/`, `models/`, or `decision/`.
- If a game/player needs an outcome-adjacent signal pre-grading (e.g. "is
  this pitcher's game live"), it must come from `raw_schedule_events` or
  `games.status`, not from box scores.

## Step 4 — Run the leakage suite and guardrails script

```
pytest engine/tests/pit
python scripts/guardrails.py
```

`scripts/guardrails.py` runs exactly the two structural checks above
(raw_* cutoff-filter usage and `raw_final_box_scores` isolation)
mechanically across the codebase — treat a guardrails failure the same as
a failing test, not an advisory warning. `engine/tests/pit/` is the suite
described in the build plan: late-arriving record excluded from a snapshot
at cutoff, as-of returns the latest pre-cutoff version, final box scores
structurally unreachable pre-grading, snapshot immutable on rerun,
walk-forward backtest never includes post-cutoff `ingested_at`, stale data
flagged not silently used, missing source produces a reason code not a
crash, conflicting sources flagged, umpire stub never blocks the pipeline,
grading refuses non-`Final` box scores. If the change touches anything
upstream of the decision engine, this suite passing is part of the
Definition of Done (`CLAUDE.md`) — not optional.

## Step 5 — Construct a concrete leaking scenario, don't just eyeball it

For any new or changed query, try to build one specific record/cutoff pair
that would leak if the code is wrong:

> "Pitcher X's probable-pitcher record has `observed_at = 2023-06-15T18:00Z`
> but was actually written (`ingested_at`) at `2023-06-15T23:50Z` — after a
> snapshot cutoff of `2023-06-15T22:00Z`. Does the query correctly exclude
> it, or does it leak because it only filtered on `observed_at`?"

If you can't construct a failing scenario, the audit isn't done — it means
you haven't tested the actual boundary condition, only confirmed the code
compiles.

## Step 6 — Report format

State explicitly: which raw_* tables were touched, whether both timestamp
filters were present for each, whether `raw_final_box_scores` isolation
holds, whether `pytest engine/tests/pit` and `scripts/guardrails.py` were
run and their result, and the concrete leak scenario you tried to construct
(and whether it succeeded or was correctly blocked).
