"""MLB probable-starter adapter -- same schedule endpoint as
ScheduleMLBAdapter (hydrated with probablePitcher), extracted into its own
adapter/raw table since a probable pitcher is a distinct, more volatile
fact than "this game exists" (starters get swapped, scratched, confirmed
late). Kept as a separate HTTP call rather than sharing one fetch with
ScheduleMLBAdapter to keep the two adapters independently pluggable/
swappable, per the adapter contract.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import httpx

from cassandra.adapters.base import AdapterFetchResult, RawRecord, SourceAdapter
from cassandra.adapters.schedule_mlb import MLB_STATS_API_BASE
from cassandra.db.models.raw import RawProbablePitcher


class ProbablePitchersMLBAdapter(SourceAdapter):
    kind = "pitcher_stats"
    source_name = "mlb_stats_api_probable_pitchers"
    adapter_version = "0.1.0"
    raw_model = RawProbablePitcher

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._client = http_client or httpx.Client(timeout=10.0)

    def fetch(self, *, slate_date: date, as_of: datetime | None = None, **kwargs: Any) -> AdapterFetchResult:
        fetched_at = datetime.now(UTC)
        try:
            response = self._client.get(
                f"{MLB_STATS_API_BASE}/schedule",
                params={
                    "sportId": 1,
                    "date": slate_date.isoformat(),
                    "hydrate": "probablePitcher",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return AdapterFetchResult(
                records=[],
                fetched_at=fetched_at,
                is_available=False,
                warnings=[f"MLB Stats API probable-pitcher fetch failed: {exc}"],
            )

        games = [g for d in payload.get("dates", []) for g in d.get("games", [])]
        records: list[RawRecord] = []
        warnings: list[str] = []
        for game in games:
            game_pk = game["gamePk"]
            for side in ("home", "away"):
                team_side = game.get("teams", {}).get(side, {})
                probable = team_side.get("probablePitcher")
                if not probable:
                    warnings.append(f"No probable pitcher listed for {side} side of game {game_pk}")
                    continue
                # "TBD"-style entries have no numeric id; treat as unconfirmed noise.
                if not probable.get("id"):
                    continue
                records.append(
                    RawRecord(
                        fields={
                            "mlb_game_pk": game_pk,
                            "player_mlb_id": probable["id"],
                            "team_mlb_id": team_side.get("team", {}).get("id"),
                            # A named, numeric-id probable pitcher in this
                            # feed IS MLB's official pregame starter
                            # listing -- the best (and, at this hydration
                            # level, only) confirmation signal available
                            # before first pitch. Previously this compared
                            # the GAME's status.abstractGameState against
                            # "Preview", which is true for essentially
                            # every game not yet in progress -- meaning
                            # is_confirmed was False for nearly every
                            # pregame listing, which fed straight into
                            # decision/engine.py's QUALITY_RISK_CODES and
                            # silently forced every pregame projection to
                            # NO_PLAY/UNCERTAIN regardless of edge. A real
                            # late scratch/swap is still caught correctly
                            # by the existing point-in-time mechanism: MLB
                            # updates this feed, a new (later observed_at)
                            # row supersedes this one, and
                            # pit/snapshot_builder.py's latest_grouped_as_of
                            # picks up whichever is current as of the
                            # freeze cutoff -- no separate "confirmed"
                            # flag is needed for that to work correctly.
                            "is_confirmed": True,
                        },
                        observed_at=fetched_at,
                        payload=probable,
                    )
                )

        if not records:
            return AdapterFetchResult(
                records=[],
                fetched_at=fetched_at,
                is_available=False,
                warnings=warnings or [f"No probable pitchers found for {slate_date.isoformat()}"],
            )
        return AdapterFetchResult(records=records, fetched_at=fetched_at, warnings=warnings)
