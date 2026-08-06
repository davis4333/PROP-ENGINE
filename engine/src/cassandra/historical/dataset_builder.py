"""Builds a versioned, frozen STRICT_LIVE_COMPATIBLE training dataset from
the historical backfill (docs/TRAINING_DATASET_SPEC.md).

Reuses the live feature-computation logic (`features/expected_bf.py`,
`features/builders.py`'s `compute_recent_k_rate`) against availability-
filtered historical inputs rather than reimplementing it -- so evaluating
the live baseline model against this dataset is a fair, apples-to-apples
comparison against what the live pipeline actually computes for a real
slate, not a parallel reimplementation that could silently drift from it.

Output is a research artifact, not a `raw_*`/`projections` table: one
gzipped JSONL file per build plus a JSON manifest, under
`data/training_datasets/` (gitignored -- see docs/TRAINING_DATASET_SPEC.md's
"Freezing and versioning" section). Deliberately not a new Postgres table:
this is wide, schema-evolving research data re-generated from already-
durable `historical_pitcher_starts` rows, not a new fact this repository
needs to guarantee append-only/immutable at the database level the way
`raw_*`/`projections`/`grades` must be -- the manifest's `dataset_id` and
frozen file give it its own immutability in practice (nothing in this
codebase ever opens an existing dataset file for writing).
"""

from __future__ import annotations

import gzip
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from itertools import groupby
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cassandra.db.models.historical import HistoricalPitcherStart, HistoricalWeatherObservation
from cassandra.db.models.identity import Game, Venue
from cassandra.features.builders import compute_recent_k_rate, compute_weather_adjustment
from cassandra.features.expected_bf import EXPECTED_BF_VERSION, compute_expected_bf
from cassandra.features.registry import FEATURE_SET_VERSION
from cassandra.historical.availability import (
    AVAILABILITY_POLICY_VERSION,
    DATASET_TIER_STRICT_LIVE_COMPATIBLE,
    eligible_prior_starts,
)
from cassandra.historical.park_factors import ParkFactorAccumulator

# Bumped from 0.1.0 to 0.2.0: park_factor/weather rows now carry real
# computed values (see park_factors.py, db/models/historical.py's
# HistoricalWeatherObservation) instead of being wholesale excluded.
# Bumped again to 0.3.0: fixed a real same-game/same-date park-factor
# leakage bug (a same-date row -- including the opposing starter in the
# SAME game -- could see another same-date row's own outcome already
# folded into its park factor; see the accumulator comment above
# build_training_dataset() for the full explanation and fix). Any dataset
# built under 0.2.0 has this bug and must not be treated as equivalent to
# one built under 0.3.0+ -- always rebuild rather than reuse a 0.2.0
# dataset for anything park-factor-sensitive (no such dataset was ever
# checked into this repository -- data/training_datasets/ is gitignored
# and no local artifact from 0.2.0 existed at the time of this fix, so
# there is nothing to migrate, only a version bump to prevent future
# confusion).
DATASET_BUILDER_VERSION = "training-dataset-builder-0.3.0"
DEFAULT_OUTPUT_DIR = Path("data/training_datasets")

# Feature groups the spec calls for that this backfill pass does not yet
# collect (docs/TRAINING_READINESS_REPORT.md) -- listed explicitly on
# every manifest so a dataset's limitations are never implied by silence.
# park_factor/weather were here through 0.1.0; both are now real (see
# park_factors.py and HistoricalWeatherObservation) so they're no longer
# blanket-excluded -- each row's own *_available flag still honestly
# reports whether this specific row actually got a resolved value.
EXCLUDED_FEATURE_GROUPS = (
    "pitch_mix",
    "velocity",
    "csw_rate",
    "opponent_rolling_k_context",
    "lineup_features",
    "umpire",
    "pitcher_handedness",
)

# Flagged explicitly on every row that has weather, not silently omitted
# (independent point-in-time-auditor review of this feature): the live
# pipeline's weather feature (`adapters/weather_openmeteo.py`) is a
# FORECAST fetched pregame -- it can be wrong (a temp swing, a storm that
# didn't materialize). This historical dataset's weather
# (`HistoricalWeatherObservation`) is MLB's own realized/ACTUAL condition
# from the completed game feed -- strictly more accurate than what the
# live pipeline could ever actually have pregame. This is not a leakage
# bug (it's still that same game's own weather, never a future game's,
# and no timestamp/cutoff is violated), but it IS a real information-
# quality mismatch: a model trained on this feature sees cleaner input
# than production ever provides it, so a training-vs-live performance gap
# attributable to weather specifically should not be surprising. No
# forecast-based historical weather source exists yet to close this gap.
WEATHER_SOURCE_ACTUAL = "actual"


@dataclass(frozen=True)
class _PriorStartShim:
    """Adapts `HistoricalPitcherStart`'s field names to the shape
    `features/expected_bf.py`/`features/builders.py`'s pure functions
    expect (`RawPitcherGameLog`'s `stat_date`/`batters_faced`/
    `strikeouts`) so this builder reuses that exact logic instead of
    reimplementing it."""

    batters_faced: int | None
    strikeouts: int | None
    stat_date: Any


def _as_shims(prior_starts: list[HistoricalPitcherStart]) -> list[_PriorStartShim]:
    return [
        _PriorStartShim(batters_faced=s.batters_faced, strikeouts=s.strikeouts, stat_date=s.game_date)
        for s in prior_starts
    ]


@dataclass(frozen=True)
class _WeatherShim:
    """Adapts `HistoricalWeatherObservation`'s `temp_f` to
    `features/builders.py`'s `WeatherLike` protocol, same reasoning as
    `_PriorStartShim` above -- reuses `compute_weather_adjustment` exactly
    as the live pipeline calls it rather than a parallel copy that could
    silently drift."""

    temp_f: float | None


@dataclass(frozen=True)
class DatasetManifest:
    dataset_id: str
    dataset_version: str
    tier: str
    seasons: list[int]
    game_types: list[str]
    availability_policy_version: str
    feature_set_version: str
    expected_bf_version: str
    dataset_builder_version: str
    built_at: str
    row_count: int
    output_path: str
    excluded_feature_groups: list[str]
    coverage_notes: dict[str, Any]


def build_training_dataset(
    session: Session,
    *,
    seasons: list[int],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    game_types: tuple[str, ...] = ("R",),
) -> DatasetManifest:
    """Builds one frozen dataset covering `seasons` (each an MLB season
    year) restricted to `game_types` (default: regular season only --
    postseason/spring/exhibition rows have different pitcher-usage
    dynamics and would bias a strikeout-props model trained for the
    regular-season market). One row per real starting-pitcher appearance
    that reached Final and has real batters-faced/strikeouts outcomes on
    record; features for that row are computed only from *that pitcher's*
    own earlier Final starts (`availability.eligible_prior_starts`) --
    never from the target game itself or any later game, which is the
    leakage guarantee this function exists to provide.
    """
    dataset_id = f"ds_{uuid.uuid4().hex[:12]}"
    built_at = datetime.now(UTC)

    stmt = (
        select(HistoricalPitcherStart, Game.game_type, Game.season, Game.venue_id)
        .join(Game, Game.mlb_game_pk == HistoricalPitcherStart.mlb_game_pk)
        .where(
            HistoricalPitcherStart.is_starter.is_(True),
            HistoricalPitcherStart.game_status == "Final",
            Game.season.in_(seasons),
            Game.game_type.in_(game_types),
            HistoricalPitcherStart.batters_faced.isnot(None),
            HistoricalPitcherStart.strikeouts.isnot(None),
        )
        .order_by(HistoricalPitcherStart.game_date.asc())
    )
    targets = session.execute(stmt).all()

    # venue_id (our string identity id) -> raw MLB venue id, for the park-
    # factor accumulator below (park_factors.py keys on the raw MLB id,
    # matching orchestration/run_slate.py's VENUE_COORDINATES convention).
    venue_id_query = select(Venue.venue_id, Venue.mlb_venue_id).where(Venue.mlb_venue_id.isnot(None))
    venue_mlb_id_by_venue_id: dict[str, int] = {
        venue_id: mlb_id for venue_id, mlb_id in session.execute(venue_id_query).all() if mlb_id is not None
    }
    # One batch query for every weather row this build could possibly need,
    # rather than one query per row -- weather_by_game_pk.get() below is a
    # dict lookup, not a DB round trip.
    game_pks = [start.mlb_game_pk for start, _, _, _ in targets]
    weather_by_game_pk: dict[int, HistoricalWeatherObservation] = {
        w.mlb_game_pk: w
        for w in session.execute(
            select(HistoricalWeatherObservation).where(HistoricalWeatherObservation.mlb_game_pk.in_(game_pks))
        )
        .scalars()
        .all()
    }
    # Chronological, DATE-GROUPED accumulator -- scoped to this build's own
    # season/game_type population (the same rows this dataset is built
    # from), not the full unrestricted historical_pitcher_starts table.
    # This means an early row in a season-restricted build (e.g.
    # seasons=[2024] only, omitting 2023) can under-report park-factor
    # availability versus a full-range build that would have more prior
    # context at the same venue -- an honest completeness gap, not a
    # leakage risk: MIN_BATTERS_FACED_FOR_PARK_FACTOR always reports
    # "unavailable" rather than ever leaking a future or out-of-scope
    # game's outcome into an early row's factor.
    #
    # Grouped by game_date (not processed row-by-row) -- found and fixed
    # after an audit: `targets` is only ordered by game_date.asc(), a
    # plain date with no secondary tiebreaker, so two starters from the
    # SAME game (home + away, same venue, same date) have no guaranteed
    # relative order. Reading-then-immediately-recording per row let
    # whichever one was processed second see the first's outcome already
    # folded into its own park factor -- a real self-referential leakage
    # bug. The conservative, provably-safe fix: every row sharing a
    # game_date reads park-factor state frozen as of the END of the PRIOR
    # date (never any other row from its own date, whether that's the
    # opposing starter in the same game or an unrelated game the same
    # day), and only after every row for that date has been written does
    # that whole date's outcomes get folded in for a STRICTLY LATER date
    # to see. This is deliberately conservative: even two games on the
    # same date that could theoretically have a provable real-world
    # ordering (one's box score final before the other's first pitch) are
    # still treated as mutually invisible, since this backfill has no
    # reliable per-game "actually became Final at wall-clock time X" data
    # to justify anything finer-grained (see docs/HISTORICAL_AVAILABILITY_
    # POLICY.md).
    park_factor_accumulator = ParkFactorAccumulator()

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{dataset_id}.jsonl.gz"

    row_count = 0
    tier_counts: dict[str, int] = {}
    park_factor_available_count = 0
    weather_available_count = 0
    with gzip.open(output_path, "wt", encoding="utf-8") as fh:
        for _game_date, date_targets_iter in groupby(targets, key=lambda t: t[0].game_date):
            date_targets = list(date_targets_iter)
            date_rows: list[dict[str, Any]] = []
            date_outcomes: list[tuple[int | None, int | None, int | None]] = []

            for start, game_type, season, venue_id in date_targets:
                prior = eligible_prior_starts(
                    session, player_mlb_id=start.player_mlb_id, before_date=start.game_date
                )
                shims = _as_shims(prior)
                bf_result = compute_expected_bf(shims)
                k_rate_result = compute_recent_k_rate(shims)
                rest_days = (start.game_date - prior[0].game_date).days if prior else None
                tier_counts[k_rate_result.tier] = tier_counts.get(k_rate_result.tier, 0) + 1

                venue_mlb_id = venue_mlb_id_by_venue_id.get(venue_id) if venue_id else None
                # Reads state frozen as of the PRIOR date only -- see the
                # accumulator comment above. Every row in this date's
                # group reads this exact same state, regardless of the
                # (arbitrary, DB-dependent) order date_targets happens to
                # iterate in.
                park_result = park_factor_accumulator.park_factor_for(venue_mlb_id)
                weather_row = weather_by_game_pk.get(start.mlb_game_pk)
                weather_temp = weather_row.temp_f if weather_row is not None else None
                weather_is_available = weather_temp is not None
                weather_adjustment = compute_weather_adjustment(
                    _WeatherShim(temp_f=float(weather_temp)) if weather_temp is not None else None
                )

                row = {
                    # Provenance -- docs/HISTORICAL_AVAILABILITY_POLICY.md's
                    # "Provenance fields every training row must carry".
                    "dataset_id": dataset_id,
                    "dataset_version": f"{DATASET_BUILDER_VERSION}+{AVAILABILITY_POLICY_VERSION}",
                    "feature_set_version": FEATURE_SET_VERSION,
                    "reconstruction_policy_version": AVAILABILITY_POLICY_VERSION,
                    # The real-world boundary eligible_prior_starts() actually
                    # enforced for this row: the target game's own date --
                    # only strictly-earlier Final starts were visible.
                    "cutoff_timestamp": start.game_date.isoformat(),
                    "capture_mode": start.capture_mode,
                    "strict_live_compatible": True,
                    "backfill_run_id": start.backfill_run_id,
                    "mlb_game_pk": start.mlb_game_pk,
                    "game_date": start.game_date.isoformat(),
                    "season": season,
                    "game_type": game_type,
                    "player_mlb_id": start.player_mlb_id,
                    "team_mlb_id": start.team_mlb_id,
                    "opponent_mlb_id": start.opponent_mlb_id,
                    "expected_bf": bf_result.value,
                    "expected_bf_tier": bf_result.tier,
                    "expected_bf_starts_used": bf_result.starts_used,
                    "recent_k_rate": k_rate_result.value,
                    "recent_k_rate_tier": k_rate_result.tier,
                    "recent_k_rate_starts_used": k_rate_result.starts_used,
                    "rest_days": rest_days,
                    "prior_starts_available": len(prior),
                    "park_k_factor": park_result.value,
                    "park_factor_available": park_result.available,
                    "weather_adjustment": weather_adjustment,
                    "weather_available": weather_is_available,
                    # WEATHER_SOURCE_ACTUAL, not omitted, when available --
                    # see that constant's docstring for why this is flagged
                    # per-row rather than silently assumed equivalent to
                    # what the live pipeline sees.
                    "weather_source": WEATHER_SOURCE_ACTUAL if weather_is_available else None,
                    # Still real gaps -- see EXCLUDED_FEATURE_GROUPS.
                    "lineup_available": False,
                    "umpire_available": False,
                    "actual_strikeouts": start.strikeouts,
                    "actual_batters_faced": start.batters_faced,
                    "actual_pitches": start.pitches_thrown,
                    "actual_innings_pitched": (
                        float(start.innings_pitched) if start.innings_pitched is not None else None
                    ),
                }
                date_rows.append(row)
                date_outcomes.append((venue_mlb_id, start.batters_faced, start.strikeouts))

            for row in date_rows:
                fh.write(json.dumps(row) + "\n")
                row_count += 1
                if row["park_factor_available"]:
                    park_factor_available_count += 1
                if row["weather_available"]:
                    weather_available_count += 1

            # AFTER every row for this date has been written -- this
            # date's outcomes become eligible for a STRICTLY LATER date's
            # park factor, never this date's own rows (see the
            # accumulator comment above for why even different games on
            # the same date are treated as mutually invisible).
            for venue_mlb_id, batters_faced, strikeouts in date_outcomes:
                park_factor_accumulator.record_outcome(venue_mlb_id, batters_faced, strikeouts)

    manifest = DatasetManifest(
        dataset_id=dataset_id,
        dataset_version=f"{DATASET_BUILDER_VERSION}+{AVAILABILITY_POLICY_VERSION}",
        tier=DATASET_TIER_STRICT_LIVE_COMPATIBLE,
        seasons=sorted(seasons),
        game_types=list(game_types),
        availability_policy_version=AVAILABILITY_POLICY_VERSION,
        feature_set_version=FEATURE_SET_VERSION,
        expected_bf_version=EXPECTED_BF_VERSION,
        dataset_builder_version=DATASET_BUILDER_VERSION,
        built_at=built_at.isoformat(),
        row_count=row_count,
        output_path=str(output_path),
        excluded_feature_groups=list(EXCLUDED_FEATURE_GROUPS),
        coverage_notes={
            "recent_k_rate_tier_counts": tier_counts,
            "park_factor_available_count": park_factor_available_count,
            "weather_available_count": weather_available_count,
        },
    )
    manifest_path = output_dir / f"{dataset_id}.manifest.json"
    manifest_path.write_text(json.dumps(asdict(manifest), indent=2))
    return manifest


def load_manifest(output_dir: Path, dataset_id: str) -> DatasetManifest:
    manifest_path = output_dir / f"{dataset_id}.manifest.json"
    data = json.loads(manifest_path.read_text())
    return DatasetManifest(**data)


def list_datasets(output_dir: Path = DEFAULT_OUTPUT_DIR) -> list[DatasetManifest]:
    if not output_dir.exists():
        return []
    manifests = []
    for path in sorted(output_dir.glob("*.manifest.json")):
        manifests.append(DatasetManifest(**json.loads(path.read_text())))
    return manifests


__all__ = [
    "DATASET_BUILDER_VERSION",
    "DEFAULT_OUTPUT_DIR",
    "EXCLUDED_FEATURE_GROUPS",
    "DatasetManifest",
    "build_training_dataset",
    "list_datasets",
    "load_manifest",
]
