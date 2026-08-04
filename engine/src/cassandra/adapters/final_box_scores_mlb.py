"""MLB final box score adapter -- feeds `raw_final_box_scores`, the outcome
data grading/ reads. Needs specific game IDs, passed via
`fetch(..., mlb_game_pks=[...])` since a single (slate_date, as_of) pair
can't express "which games."

Writes one record per pitcher who appears in the live-feed boxscore with
any pitching stats, regardless of the game's current status -- a row for
a still-`Live` or `Preview` game is legitimate (useful for the Admin
view's pipeline visibility) and simply isn't a candidate for grading yet;
`grading/service.py` is the only place that filters to `game_status ==
'Final'` (ADR 0007).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import httpx

from cassandra.adapters.base import AdapterFetchResult, RawRecord, SourceAdapter
from cassandra.db.models.raw import RawFinalBoxScore

LIVE_FEED_BASE = "https://statsapi.mlb.com/api/v1.1"


def _parse_innings_pitched(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


class FinalBoxScoresMLBAdapter(SourceAdapter):
    kind = "pitcher_stats"
    source_name = "mlb_stats_api_final_box_scores"
    adapter_version = "0.1.0"
    raw_model = RawFinalBoxScore

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._client = http_client or httpx.Client(timeout=10.0)

    def fetch(self, *, slate_date: date, as_of: datetime | None = None, **kwargs: Any) -> AdapterFetchResult:
        fetched_at = datetime.now(UTC)
        mlb_game_pks: list[int] = kwargs.get("mlb_game_pks") or []
        if not mlb_game_pks:
            return AdapterFetchResult(
                records=[],
                fetched_at=fetched_at,
                is_available=False,
                warnings=["No mlb_game_pks supplied -- nothing to fetch box scores for"],
            )

        records: list[RawRecord] = []
        warnings: list[str] = []
        for game_pk in mlb_game_pks:
            try:
                response = self._client.get(f"{LIVE_FEED_BASE}/game/{game_pk}/feed/live")
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                warnings.append(f"Live feed fetch failed for game {game_pk}: {exc}")
                continue

            game_status = payload.get("gameData", {}).get("status", {}).get("abstractGameState", "Unknown")
            teams = payload.get("liveData", {}).get("boxscore", {}).get("teams", {})
            found_pitcher = False
            for side in ("home", "away"):
                players = teams.get(side, {}).get("players", {})
                for player_entry in players.values():
                    pitching = player_entry.get("stats", {}).get("pitching") or {}
                    if not pitching:
                        continue
                    found_pitcher = True
                    person = player_entry.get("person", {})
                    records.append(
                        RawRecord(
                            fields={
                                "mlb_game_pk": game_pk,
                                "player_mlb_id": person.get("id"),
                                "strikeouts_recorded": pitching.get("strikeOuts"),
                                "innings_pitched": _parse_innings_pitched(pitching.get("inningsPitched")),
                                "pitch_count": pitching.get("numberOfPitches"),
                                "game_status": game_status,
                            },
                            observed_at=fetched_at,
                            payload={"person": person, "pitching": pitching, "game_status": game_status},
                        )
                    )
            if not found_pitcher:
                warnings.append(
                    f"No pitching lines found in boxscore for game {game_pk} (status={game_status})"
                )

        if not records:
            return AdapterFetchResult(
                records=[],
                fetched_at=fetched_at,
                is_available=False,
                warnings=warnings or ["No box score records found"],
            )
        return AdapterFetchResult(records=records, fetched_at=fetched_at, warnings=warnings)
