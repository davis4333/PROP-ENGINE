"""Static park-factor adapter -- no HTTP, no live vendor. Park strikeout
factors are slow-moving (they don't need a point-in-time feed), so a
seeded reference table is a legitimate permanent source, not just an MVP
shortcut -- see CURRENT_STATE_AUDIT.md.

**The K-factor values below are illustrative approximations, not sourced
from a licensed park-factor vendor.** They exist to prove the adjustment
mechanism end-to-end (see the baseline model's `park_adj`). Replace with a
real, cited park-factor source before treating any resulting projection
as more than a demo. Only `venue_id=2` (Oriole Park at Camden Yards,
confirmed against the real MLB Stats API during development, used by the
fixture demo slate) is verified; the rest are common approximations kept
deliberately unclaimed as authoritative. Unknown venues fall back to a
neutral 1.00 factor with a warning rather than guessing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from cassandra.adapters.base import AdapterFetchResult, RawRecord, SourceAdapter
from cassandra.db.models.raw import RawParkFactor
from cassandra.identity_ids import mlb_venue_id

NEUTRAL_K_FACTOR = 1.00

# MLB venue_id -> approximate strikeout park factor (1.00 = neutral).
STATIC_PARK_K_FACTORS: dict[int, float] = {
    2: 1.00,  # Oriole Park at Camden Yards (Baltimore) -- verified venue_id
    3: 0.97,  # Fenway Park (Boston)
    5: 1.02,  # Angel Stadium (LA Angels)
    7: 1.05,  # Chase Field (Arizona)
    10: 0.98,  # Guaranteed Rate Field (Chicago White Sox)
    12: 0.96,  # Great American Ball Park (Cincinnati)
    15: 1.06,  # Minute Maid Park (Houston)
    17: 1.00,  # Wrigley Field (Chicago Cubs)
    19: 0.90,  # Coors Field (Colorado) -- thin air, typically fewer strikeouts
    22: 1.04,  # Dodger Stadium (LA Dodgers)
    31: 1.03,  # Kauffman Stadium (Kansas City)
}


class ParkFactorsStaticAdapter(SourceAdapter):
    kind = "park"
    source_name = "park_factors_static"
    adapter_version = "0.1.0"
    raw_model = RawParkFactor

    def fetch(self, *, slate_date: date, as_of: datetime | None = None, **kwargs: Any) -> AdapterFetchResult:
        fetched_at = datetime.now(UTC)
        venue_ids: list[int] = kwargs.get("venue_ids") or list(STATIC_PARK_K_FACTORS)
        # observed_at is intentionally the start of the season, not "now" --
        # a park factor is a slow-moving, season-scoped fact, and pinning it
        # to season start keeps the as-of semantics honest for backtests.
        season_start = datetime(slate_date.year, 1, 1, tzinfo=UTC)

        records: list[RawRecord] = []
        warnings: list[str] = []
        for venue_id in venue_ids:
            k_factor = STATIC_PARK_K_FACTORS.get(venue_id)
            if k_factor is None:
                warnings.append(
                    f"No seeded park factor for venue_id={venue_id}; defaulting to neutral {NEUTRAL_K_FACTOR}"
                )
                k_factor = NEUTRAL_K_FACTOR
            records.append(
                RawRecord(
                    fields={
                        "venue_id": mlb_venue_id(venue_id),
                        "season": slate_date.year,
                        "k_factor": k_factor,
                    },
                    observed_at=season_start,
                    payload={"venue_id": venue_id, "k_factor": k_factor, "source": "static_seed"},
                )
            )
        return AdapterFetchResult(records=records, fetched_at=fetched_at, warnings=warnings)
