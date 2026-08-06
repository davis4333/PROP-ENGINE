# Historical Availability Policy

**Status: implemented for `STRICT_LIVE_COMPATIBLE`, rules 1-2 and 6-7
below** (`historical/availability.py`'s `eligible_prior_starts()`,
consumed by `historical/dataset_builder.py` — see `TRAINING_DATASET_SPEC.md`
and `TRAINING_READINESS_REPORT.md`). Rules 3-5 (lineup/weather/umpire
exclusion) are enforced by omission, not by code that would otherwise
include them — this backfill pass doesn't collect that data at all yet,
so there is nothing for the builder to accidentally include. Every
dataset manifest and row records `park_factor_available`,
`weather_available`, `lineup_available`, `umpire_available` (currently
always `False`) so this is checkable, not assumed.
`RETROSPECTIVE_ENRICHED` remains unimplemented (nothing enriched exists
yet to build it from).

## The problem this solves

The live pipeline's leakage gate (`pit/asof.py`) answers "what did
Cassandra actually know before cutoff?" using `ingested_at` — physical
write time. A historical backfill's `ingested_at` is always "whenever
the backfill ran," which is useless for that question when reconstructing
a 2023 game in 2026 (see `HISTORICAL_BACKFILL_DESIGN.md`). Training on
historical data still needs an honest notion of "what was knowable before
this game," just derived a different way: from the real world's own
timeline, not from when *we* happened to fetch it.

## Two dataset tiers

### `STRICT_LIVE_COMPATIBLE`

Contains only features Cassandra could reasonably reproduce for a real
future live game, using the *actual* live pipeline's data-availability
constraints. **This must be the default for training and model
comparison.**

Rules:

1. **Prior-game statistics** (a pitcher's own recent starts, an
   opponent's recent strikeout rate) are eligible only once the prior
   game the stat is drawn from reached `Final` status, and only for
   games strictly before the target game's date. This mirrors the live
   pipeline's own `pit/asof.py` cutoff semantics, just anchored to game
   completion rather than `ingested_at`.
2. **The target game's own outcome is never eligible** as a feature,
   under any framing — not batters faced, not pitch count, not innings
   pitched, nothing derived from the game being predicted.
3. **Actual same-game lineup is excluded** from this tier. The free MLB
   Stats API's historical data doesn't reliably preserve a trustworthy
   pregame-availability timestamp for lineups the way it does for, say,
   a game's final status — `historical_lineups.capture_mode` is always
   `HISTORICAL_ACTUAL`, meaning "this is the real final lineup," not "this
   is what was posted before first pitch." Using it in this tier would
   silently grant the model information a live run would never have had
   this early.
4. **Actual historical weather is excluded** unless it comes from a
   historical *forecast* issued before the game (not yet collected by
   this backfill at all — see the design doc's "out of scope" list).
   Retrospective/actual weather is a different signal than what a live
   run would have seen pregame, and conflating them would overstate the
   model's real forecasting power.
5. **Final umpire information is retrospective** unless pregame
   availability can be established — same reasoning as weather. (Not
   collected by this backfill.)
6. **Identity data may be used as identity, never as postgame
   performance information.** E.g. "this is Pitcher X" is fine at any
   time; "Pitcher X allowed 2 earned runs today" is not usable as a
   feature for predicting Pitcher X's strikeouts *in that same start*.
7. A pitcher's actual starter status (`is_starter`) for the **target**
   game is identity/context (who is this row about), not a leaked
   outcome — using it to select which rows become training examples is
   fine; the concern above is about using post-game *performance* facts.

### `RETROSPECTIVE_ENRICHED`

May include clearly labeled retrospective context (actual lineups, actual
weather, anything excluded from the strict tier above) for research
purposes — e.g. "how much would knowing the real lineup have helped, if
we'd had it." **Must never be confused with, merged into, or used to
claim live betting performance for the strict tier.** Every row and every
report generated from this tier must be labeled `RETROSPECTIVE_ENRICHED`
or `HISTORICAL_RECONSTRUCTION`, never `LIVE`.

## Provenance fields every training row must carry (once built)

Per the mission directive's required minimum fields (see
`TRAINING_DATASET_SPEC.md`): `dataset_version`, `feature_set_version`,
`reconstruction_policy_version` (this document's own version — bump it
whenever a rule above changes), `cutoff_timestamp` (the real-world
moment used as the availability boundary for this row, per rule 1 above),
`capture_mode`, `strict_live_compatible` boolean, `backfill_run_id`,
source coverage flags, and missingness indicators.

## Labeling requirement for anything produced under this policy

Per the mission directive's non-negotiable #4: historical model
evaluations must never appear as live Cassandra selections. Every
historical prediction, simulation, or reconstructed evaluation must be
labeled `BACKTEST`, `HISTORICAL_RECONSTRUCTION`, or `PAPER` — never
`LIVE` — in whatever table or report contains it. The public results
ledger (`projections`/`grades`) is exclusively for real, live, published
Cassandra decisions; nothing produced by a backtest or historical
evaluation may be written there.
