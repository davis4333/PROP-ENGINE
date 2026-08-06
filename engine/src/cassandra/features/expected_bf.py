"""Expected-batters-faced calculation -- versioned independently of
`feature_set_version` (ADR 0004), with an explicit, visible fallback
chain rather than a silent default.

Fallback chain actually implemented in this MVP:
1. Decay-weighted average of batters faced over the pitcher's recent
   starts this season (tier="recent_weighted"), if at least
   `MIN_STARTS_FOR_RECENT` valid starts exist.
2. Plain season-to-date average, if 1-2 valid starts exist
   (tier="season_average").
3. A league-average-starter default (tier="league_default"), if zero
   valid starts exist this season.

ADR 0004 also specifies a third tier -- career average for pitchers in a
similar role -- ahead of the league default. That specific tier (role-
similarity clustering) is **not implemented**. What is implemented:
`PitcherGameLogsMLBAdapter` falls back to the prior season's game logs
when the current season has fewer than its own `FALLBACK_SEASON_MIN_STARTS`
valid starts (early season, an injury/rehab return, a mid-season call-up),
so this module still only ever sees one already-merged, cutoff-filtered
list -- it has no notion of which season a given start came from, and
doesn't need one. Falling through to `league_default` only happens when
there's truly no usable history in either season (see
CURRENT_STATE_AUDIT.md) -- `tier` is always recorded on the result and
surfaced in the feature blob, never a silent gap.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class GameLogLike(Protocol):
    """Structural contract this module (and `features/builders.py`'s
    decay-weighted helpers) actually needs from a "prior start" record --
    satisfied by `RawPitcherGameLog` (the live pipeline's input) and by
    `historical/dataset_builder.py`'s `_PriorStartShim` (the historical
    training-dataset builder's input), so both callers can reuse this
    exact computation logic instead of maintaining their own copies.

    Declared as read-only properties, not plain attributes: a Protocol's
    plain attributes are invariant (implying both get *and* set access),
    which would reject an implementer whose field type is narrower than
    this Protocol's (e.g. `_PriorStartShim.stat_date: date` vs. this
    Protocol's `date | datetime`) even though every real use here only
    ever reads these fields.
    """

    @property
    def batters_faced(self) -> int | None: ...
    @property
    def strikeouts(self) -> int | None: ...
    @property
    def stat_date(self) -> date | datetime: ...


EXPECTED_BF_VERSION = "expected-bf-0.1.0"

# Illustrative, not sourced from a vendor -- see CURRENT_STATE_AUDIT.md.
LEAGUE_AVG_STARTER_BF = 23.0

MIN_STARTS_FOR_RECENT = 3
DECAY_HALF_LIFE_STARTS = 3.0


@dataclass(frozen=True)
class ExpectedBFResult:
    value: float
    tier: str  # "recent_weighted" | "season_average" | "league_default"
    starts_used: int
    version: str = EXPECTED_BF_VERSION


def compute_expected_bf(game_logs_latest_first: Sequence[GameLogLike]) -> ExpectedBFResult:
    valid_bf: list[int] = [g.batters_faced for g in game_logs_latest_first if g.batters_faced is not None]

    if len(valid_bf) >= MIN_STARTS_FOR_RECENT:
        weights = [0.5 ** (i / DECAY_HALF_LIFE_STARTS) for i in range(len(valid_bf))]
        weighted_sum = sum(w * bf for w, bf in zip(weights, valid_bf, strict=True))
        return ExpectedBFResult(
            value=weighted_sum / sum(weights), tier="recent_weighted", starts_used=len(valid_bf)
        )

    if valid_bf:
        avg = sum(valid_bf) / len(valid_bf)
        return ExpectedBFResult(value=avg, tier="season_average", starts_used=len(valid_bf))

    return ExpectedBFResult(value=LEAGUE_AVG_STARTER_BF, tier="league_default", starts_used=0)
