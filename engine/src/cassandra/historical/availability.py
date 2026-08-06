"""Historical-reconstruction availability policy (docs/HISTORICAL_AVAILABILITY_POLICY.md).

Defines which historical facts a training-dataset row is allowed to draw
on, so a built dataset honestly reflects "what could Cassandra have known
before this game's first pitch" -- not the live pipeline's
`ingested_at`-based `pit/asof.py` gate (structurally inapplicable here;
see db/models/historical.py's module docstring for why), but a
real-world-timeline-based one: a fact about a prior game only becomes
eligible once that prior game itself reached Final, and the prior game
must have happened strictly before the target game's date.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from cassandra.db.models.historical import HistoricalPitcherStart

AVAILABILITY_POLICY_VERSION = "historical-availability-0.1.0"

# STRICT_LIVE_COMPATIBLE: only feature groups a live pregame run could
# plausibly have populated, further restricted to what this backfill pass
# actually collects today (docs/TRAINING_DATASET_SPEC.md). RETROSPECTIVE_
# ENRICHED is documented as a future tier (lineup/park/weather/pitch-level
# data once collected) -- deliberately not implemented as an alias for
# this one, since there is nothing enriched to include yet.
DATASET_TIER_STRICT_LIVE_COMPATIBLE = "STRICT_LIVE_COMPATIBLE"

# Matches PitcherGameLogsMLBAdapter's own recent-starts lookback so the
# historical reconstruction sees the same amount of history a live
# pregame run would have had access to.
MAX_PRIOR_STARTS_CONSIDERED = 10


def eligible_prior_starts(
    session: Session, *, player_mlb_id: int, before_date: date
) -> list[HistoricalPitcherStart]:
    """Every fact a STRICT_LIVE_COMPATIBLE row is allowed to see about this
    pitcher's own prior form: real starts that themselves reached Final,
    strictly before the target game's date -- ordered most recent first
    (the ordering `features/expected_bf.py` and `features/builders.py`'s
    decay-weighting functions require). The `game_date < before_date`
    filter is what makes this function the dataset builder's leakage
    gate -- it structurally cannot return the target game itself or
    anything on/after its date.
    """
    stmt = (
        select(HistoricalPitcherStart)
        .where(
            HistoricalPitcherStart.player_mlb_id == player_mlb_id,
            HistoricalPitcherStart.is_starter.is_(True),
            HistoricalPitcherStart.game_status == "Final",
            HistoricalPitcherStart.game_date < before_date,
        )
        .order_by(HistoricalPitcherStart.game_date.desc())
        .limit(MAX_PRIOR_STARTS_CONSIDERED)
    )
    return list(session.execute(stmt).scalars().all())


__all__ = [
    "AVAILABILITY_POLICY_VERSION",
    "DATASET_TIER_STRICT_LIVE_COMPATIBLE",
    "MAX_PRIOR_STARTS_CONSIDERED",
    "eligible_prior_starts",
]
