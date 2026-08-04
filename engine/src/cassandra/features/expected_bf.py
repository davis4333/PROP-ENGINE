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
similar role -- ahead of the league default. That tier is **not
implemented**: it would need multi-season game-log history, and this
MVP's `PitcherGameLogsMLBAdapter` only fetches the current season (see
CURRENT_STATE_AUDIT.md). Falling through straight to `league_default`
when season data is too thin is an honest simplification, not a silent
gap -- `tier` is always recorded on the result and surfaced in the
feature blob.
"""

from __future__ import annotations

from dataclasses import dataclass

from cassandra.db.models.raw import RawPitcherGameLog

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


def compute_expected_bf(game_logs_latest_first: list[RawPitcherGameLog]) -> ExpectedBFResult:
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
