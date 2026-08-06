"""Point-in-time-safe park-factor computation for the STRICT_LIVE_COMPATIBLE
training dataset -- docs/HISTORICAL_BACKFILL_DESIGN.md's "Park factors
calculated from prior completed games (rather than the live pipeline's
small static table) -- designed, not implemented" item, now implemented.

A park factor for game G at venue V is (strikeout rate at V, from every
Final start played at V strictly before G) divided by (league-wide
strikeout rate from every Final start anywhere strictly before G) --
clipped to the same band `models/baseline.py`'s `PARK_ADJ_BOUNDS` already
uses live, so a model consuming this field never needs to guess a
different clipping convention than the one it'll see in production.

Computed via a single forward accumulator over `historical_pitcher_starts`
rows in chronological order (`dataset_builder.py` already sorts its target
query by `game_date.asc()`) rather than a separate DB query per row -- one
pass instead of N additional round trips, and point-in-time-safe by
construction: `park_factor_for` must be read before `record_outcome` is
called for that same row, so a game can never contribute to its own park
factor or to any earlier game's.
"""

from __future__ import annotations

from dataclasses import dataclass

# Roughly half a home season's worth of batters faced at one park --
# below this, a venue's own sample is too thin to trust over the league
# average, so the factor reports unavailable (neutral) rather than a
# noisy early-season estimate.
MIN_BATTERS_FACED_FOR_PARK_FACTOR = 400

# Matches models/baseline.py's PARK_ADJ_BOUNDS -- one shared clipping
# convention between the historical dataset and the live model.
PARK_FACTOR_BOUNDS = (0.85, 1.15)
NEUTRAL_PARK_FACTOR = 1.00


@dataclass(frozen=True)
class ParkFactorResult:
    value: float
    available: bool
    venue_batters_faced: int


class ParkFactorAccumulator:
    """Stateful, chronological-order-only accumulator. Callers must call
    `park_factor_for` for a row before `record_outcome` for that same row,
    and must process rows in non-decreasing `game_date` order -- calling
    them out of order would let a game see its own or a later game's
    outcome, defeating the entire point of this class."""

    def __init__(self) -> None:
        self._venue_bf: dict[int, int] = {}
        self._venue_k: dict[int, int] = {}
        self._league_bf = 0
        self._league_k = 0

    def park_factor_for(self, venue_mlb_id: int | None) -> ParkFactorResult:
        if venue_mlb_id is None or self._league_bf == 0:
            return ParkFactorResult(value=NEUTRAL_PARK_FACTOR, available=False, venue_batters_faced=0)
        venue_bf = self._venue_bf.get(venue_mlb_id, 0)
        if venue_bf < MIN_BATTERS_FACED_FOR_PARK_FACTOR:
            return ParkFactorResult(value=NEUTRAL_PARK_FACTOR, available=False, venue_batters_faced=venue_bf)
        league_k_rate = self._league_k / self._league_bf
        if league_k_rate <= 0:
            return ParkFactorResult(value=NEUTRAL_PARK_FACTOR, available=False, venue_batters_faced=venue_bf)
        venue_k_rate = self._venue_k[venue_mlb_id] / venue_bf
        raw = venue_k_rate / league_k_rate
        lo, hi = PARK_FACTOR_BOUNDS
        clipped = max(lo, min(hi, raw))
        return ParkFactorResult(value=clipped, available=True, venue_batters_faced=venue_bf)

    def record_outcome(
        self, venue_mlb_id: int | None, batters_faced: int | None, strikeouts: int | None
    ) -> None:
        if venue_mlb_id is None or batters_faced is None or strikeouts is None:
            return
        self._venue_bf[venue_mlb_id] = self._venue_bf.get(venue_mlb_id, 0) + batters_faced
        self._venue_k[venue_mlb_id] = self._venue_k.get(venue_mlb_id, 0) + strikeouts
        self._league_bf += batters_faced
        self._league_k += strikeouts


__all__ = [
    "MIN_BATTERS_FACED_FOR_PARK_FACTOR",
    "NEUTRAL_PARK_FACTOR",
    "PARK_FACTOR_BOUNDS",
    "ParkFactorAccumulator",
    "ParkFactorResult",
]
