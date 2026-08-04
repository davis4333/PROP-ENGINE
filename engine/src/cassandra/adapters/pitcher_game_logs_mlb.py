"""MLB pitcher game-log adapter -- recent-starts workload/strikeout history
feeding the baseline model's features. Needs specific player IDs (the
probable pitchers already resolved for this slate), passed via
`fetch(..., player_mlb_ids=[...])` since a single (slate_date, as_of)
pair can't express "which pitchers."
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import httpx

from cassandra.adapters.base import AdapterFetchResult, RawRecord, SourceAdapter
from cassandra.adapters.schedule_mlb import MLB_STATS_API_BASE
from cassandra.db.models.raw import RawPitcherGameLog


class PitcherGameLogsMLBAdapter(SourceAdapter):
    kind = "pitcher_stats"
    source_name = "mlb_stats_api_pitcher_game_logs"
    adapter_version = "0.1.0"
    raw_model = RawPitcherGameLog

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._client = http_client or httpx.Client(timeout=10.0)

    def fetch(self, *, slate_date: date, as_of: datetime | None = None, **kwargs: Any) -> AdapterFetchResult:
        fetched_at = datetime.now(UTC)
        player_mlb_ids: list[int] = kwargs.get("player_mlb_ids") or []
        if not player_mlb_ids:
            return AdapterFetchResult(
                records=[],
                fetched_at=fetched_at,
                is_available=False,
                warnings=["No player_mlb_ids supplied -- nothing to fetch game logs for"],
            )

        records: list[RawRecord] = []
        warnings: list[str] = []
        for player_id in player_mlb_ids:
            try:
                response = self._client.get(
                    f"{MLB_STATS_API_BASE}/people/{player_id}/stats",
                    params={"stats": "gameLog", "group": "pitching", "season": slate_date.year},
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                warnings.append(f"Game log fetch failed for player {player_id}: {exc}")
                continue

            stat_groups = payload.get("stats", [])
            splits = stat_groups[0].get("splits", []) if stat_groups else []
            for split in splits:
                game_date = split.get("date")
                if not game_date or game_date >= slate_date.isoformat():
                    # Only prior starts belong in a pitcher's own history --
                    # this isn't the leakage gate itself (ingested_at is,
                    # per ADR 0001) but there's no reason to even ingest a
                    # same-day-or-later "prior start."
                    continue
                stat = split.get("stat", {})
                records.append(
                    RawRecord(
                        fields={
                            "player_mlb_id": player_id,
                            "mlb_game_pk": split.get("game", {}).get("gamePk"),
                            "stat_date": game_date,
                            "batters_faced": stat.get("battersFaced"),
                            "strikeouts": stat.get("strikeOuts"),
                            "pitch_count": stat.get("numberOfPitches"),
                            "innings_pitched": stat.get("inningsPitched"),
                        },
                        observed_at=fetched_at,
                        payload=split,
                    )
                )

        if not records:
            return AdapterFetchResult(
                records=[],
                fetched_at=fetched_at,
                is_available=False,
                warnings=warnings or ["No prior game log entries found"],
            )
        return AdapterFetchResult(records=records, fetched_at=fetched_at, warnings=warnings)
