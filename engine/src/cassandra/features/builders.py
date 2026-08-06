"""Builds the `feature_values.features` blob for one pitcher-slate entry
(see pit/snapshot_builder.py's `PitcherSlateEntry`) -- pure computation
over already as-of-resolved data, no querying here. See
features/registry.py for what each field means.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

from cassandra.features.expected_bf import (
    DECAY_HALF_LIFE_STARTS,
    MIN_STARTS_FOR_RECENT,
    GameLogLike,
    compute_expected_bf,
)
from cassandra.features.registry import FEATURE_SET_VERSION
from cassandra.pit.snapshot_builder import PitcherSlateEntry

NEUTRAL_PARK_FACTOR = 1.00
NEUTRAL_WEATHER_ADJUSTMENT = 1.00
LEAGUE_AVG_K_RATE = 0.22  # ~22% K/BF, illustrative -- see CURRENT_STATE_AUDIT.md

# Reserved seam for a future opponent-lineup-contact-rate adjustment --
# see features/registry.py's opponent_adjustment entry.
NEUTRAL_OPPONENT_ADJUSTMENT = 1.00


@runtime_checkable
class WeatherLike(Protocol):
    """Structural contract `compute_weather_adjustment` actually needs --
    satisfied by `RawWeatherObservation` (the live pipeline's input) and by
    `historical/dataset_builder.py`'s weather shim (the historical
    training-dataset builder's input), same reasoning as
    `expected_bf.py`'s `GameLogLike`: one shared computation, no risk of
    the historical dataset's weather adjustment silently drifting from
    what the live pipeline actually computes."""

    @property
    def temp_f(self) -> float | None: ...


@dataclass(frozen=True)
class KRateResult:
    value: float
    tier: str
    starts_used: int


def compute_recent_k_rate(game_logs_latest_first: Sequence[GameLogLike]) -> KRateResult:
    valid: list[tuple[int, int]] = [
        (g.batters_faced, g.strikeouts)
        for g in game_logs_latest_first
        if g.batters_faced and g.strikeouts is not None
    ]
    if len(valid) >= MIN_STARTS_FOR_RECENT:
        weights = [0.5 ** (i / DECAY_HALF_LIFE_STARTS) for i in range(len(valid))]
        weighted_k = sum(w * k for w, (_, k) in zip(weights, valid, strict=True))
        weighted_bf = sum(w * bf for w, (bf, _) in zip(weights, valid, strict=True))
        return KRateResult(value=weighted_k / weighted_bf, tier="recent_weighted", starts_used=len(valid))
    if valid:
        total_k = sum(k for _, k in valid)
        total_bf = sum(bf for bf, _ in valid)
        return KRateResult(value=total_k / total_bf, tier="season_average", starts_used=len(valid))
    return KRateResult(value=LEAGUE_AVG_K_RATE, tier="league_default", starts_used=0)


def compute_weather_adjustment(weather: WeatherLike | None) -> float:
    """A small, bounded, illustrative adjustment -- not a calibrated
    model. Cold weather (thicker air, less carry) is treated as a mild
    boost to strikeout likelihood; hot weather a mild reduction. See
    features/registry.py."""
    if weather is None or weather.temp_f is None:
        return NEUTRAL_WEATHER_ADJUSTMENT
    temp = float(weather.temp_f)
    if temp >= 85:
        return 0.98
    if temp <= 50:
        return 1.02
    return NEUTRAL_WEATHER_ADJUSTMENT


def compute_rest_days(game_logs_latest_first: Sequence[GameLogLike], cutoff_at: datetime) -> int | None:
    if not game_logs_latest_first:
        return None
    most_recent = game_logs_latest_first[0]
    stat_date = most_recent.stat_date
    if isinstance(stat_date, datetime):
        last_start_date = stat_date.date()
    elif isinstance(stat_date, date):
        last_start_date = stat_date
    else:
        return None
    return (cutoff_at.date() - last_start_date).days


def build_features(entry: PitcherSlateEntry, cutoff_at: datetime) -> dict[str, Any]:
    # compute_expected_bf/compute_recent_k_rate/compute_rest_days all
    # assume "latest start first" (their decay-weighting indexes by
    # recency rank). entry.game_logs comes from pit/asof.py's
    # all_as_of(), ordered by (observed_at, ingested_at) -- but every
    # game-log row from a single adapter fetch shares the same
    # observed_at/ingested_at (both stamped once per fetch call, not
    # per historical start), so that ordering has no power to rank the
    # starts themselves by actual recency. Sorting explicitly by
    # stat_date here is what actually satisfies the "latest first"
    # contract these functions rely on.
    game_logs_latest_first = sorted(entry.game_logs, key=lambda g: g.stat_date, reverse=True)
    bf_result = compute_expected_bf(game_logs_latest_first)
    k_rate_result = compute_recent_k_rate(game_logs_latest_first)
    park_k_factor = float(entry.park_factor.k_factor) if entry.park_factor else NEUTRAL_PARK_FACTOR
    weather_adjustment = compute_weather_adjustment(entry.weather)
    rest_days = compute_rest_days(game_logs_latest_first, cutoff_at)

    weak_sample = bf_result.tier != "recent_weighted" or k_rate_result.tier != "recent_weighted"

    return {
        "expected_bf": bf_result.value,
        "expected_bf_tier": bf_result.tier,
        "expected_bf_version": bf_result.version,
        "expected_bf_starts_used": bf_result.starts_used,
        "recent_k_rate": k_rate_result.value,
        "recent_k_rate_tier": k_rate_result.tier,
        "recent_k_rate_starts_used": k_rate_result.starts_used,
        "park_k_factor": park_k_factor,
        "park_factor_available": entry.park_factor is not None,
        "weather_adjustment": weather_adjustment,
        "weather_available": entry.weather is not None,
        "rest_days": rest_days,
        "umpire_available": False,
        "role_stability_flag": weak_sample,
        "opponent_adjustment": NEUTRAL_OPPONENT_ADJUSTMENT,
    }


__all__ = ["FEATURE_SET_VERSION", "build_features", "compute_recent_k_rate", "compute_weather_adjustment"]
