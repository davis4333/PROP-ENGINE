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
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cassandra.db.models.historical import HistoricalPitcherStart
from cassandra.db.models.identity import Game
from cassandra.features.builders import compute_recent_k_rate
from cassandra.features.expected_bf import EXPECTED_BF_VERSION, compute_expected_bf
from cassandra.features.registry import FEATURE_SET_VERSION
from cassandra.historical.availability import (
    AVAILABILITY_POLICY_VERSION,
    DATASET_TIER_STRICT_LIVE_COMPATIBLE,
    eligible_prior_starts,
)

DATASET_BUILDER_VERSION = "training-dataset-builder-0.1.0"
DEFAULT_OUTPUT_DIR = Path("data/training_datasets")

# Feature groups the spec calls for that this backfill pass does not yet
# collect (docs/TRAINING_READINESS_REPORT.md) -- listed explicitly on
# every manifest so a dataset's limitations are never implied by silence.
EXCLUDED_FEATURE_GROUPS = (
    "pitch_mix",
    "velocity",
    "csw_rate",
    "park_factor",
    "weather",
    "opponent_rolling_k_context",
    "lineup_features",
    "umpire",
    "pitcher_handedness",
)


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
        select(HistoricalPitcherStart, Game.game_type, Game.season)
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

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{dataset_id}.jsonl.gz"

    row_count = 0
    tier_counts: dict[str, int] = {}
    with gzip.open(output_path, "wt", encoding="utf-8") as fh:
        for start, game_type, season in targets:
            prior = eligible_prior_starts(
                session, player_mlb_id=start.player_mlb_id, before_date=start.game_date
            )
            shims = _as_shims(prior)
            bf_result = compute_expected_bf(shims)
            k_rate_result = compute_recent_k_rate(shims)
            rest_days = (start.game_date - prior[0].game_date).days if prior else None
            tier_counts[k_rate_result.tier] = tier_counts.get(k_rate_result.tier, 0) + 1

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
                # Source coverage flags -- always False in this pass, per
                # excluded_feature_groups below; never silently omitted.
                "park_factor_available": False,
                "weather_available": False,
                "lineup_available": False,
                "umpire_available": False,
                "actual_strikeouts": start.strikeouts,
                "actual_batters_faced": start.batters_faced,
                "actual_pitches": start.pitches_thrown,
                "actual_innings_pitched": (
                    float(start.innings_pitched) if start.innings_pitched is not None else None
                ),
            }
            fh.write(json.dumps(row) + "\n")
            row_count += 1

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
        coverage_notes={"recent_k_rate_tier_counts": tier_counts},
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
