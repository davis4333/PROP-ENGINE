"""MLB schedule adapter -- free, public, no key (statsapi.mlb.com)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import httpx

from cassandra.adapters.base import AdapterFetchResult, RawRecord, SourceAdapter
from cassandra.db.models.raw import RawScheduleEvent

MLB_STATS_API_BASE = "https://statsapi.mlb.com/api/v1"


class ScheduleMLBAdapter(SourceAdapter):
    kind = "schedule"
    source_name = "mlb_stats_api_schedule"
    adapter_version = "0.1.0"
    raw_model = RawScheduleEvent

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
                    "hydrate": "team,venue,probablePitcher",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return AdapterFetchResult(
                records=[],
                fetched_at=fetched_at,
                is_available=False,
                warnings=[f"MLB Stats API schedule fetch failed: {exc}"],
            )

        games = [g for d in payload.get("dates", []) for g in d.get("games", [])]
        if not games:
            return AdapterFetchResult(
                records=[],
                fetched_at=fetched_at,
                is_available=False,
                warnings=[f"No games returned for {slate_date.isoformat()}"],
            )

        records = [
            RawRecord(
                fields={"mlb_game_pk": game["gamePk"]},
                observed_at=fetched_at,
                payload=game,
            )
            for game in games
        ]
        return AdapterFetchResult(records=records, fetched_at=fetched_at)
