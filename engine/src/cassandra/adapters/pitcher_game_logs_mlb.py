"""MLB pitcher game-log adapter -- recent-starts workload/strikeout history
feeding the baseline model's features. Needs specific player IDs (the
probable pitchers already resolved for this slate), passed via
`fetch(..., player_mlb_ids=[...])` since a single (slate_date, as_of)
pair can't express "which pitchers."

Fetches the slate's own season by default; if a pitcher has fewer than
`FALLBACK_SEASON_MIN_STARTS` valid starts there (early season, a rehab/
injury return, a mid-season call-up), also fetches the prior season and
merges it in -- otherwise `features/expected_bf.py` and
`features/builders.py`'s `compute_recent_k_rate` would fall straight to
a generic league-average default for a pitcher who actually has a
perfectly good multi-year track record one more request away. This is
the "prior season" half of ADR 0004's fallback chain; the full "career
average for pitchers in a similar role" tier it also describes remains
unimplemented (that needs role-similarity clustering, not just more raw
history) -- see CURRENT_STATE_AUDIT.md.
`FALLBACK_SEASON_MIN_STARTS` intentionally mirrors (rather than imports)
`features/expected_bf.py`'s `MIN_STARTS_FOR_RECENT` -- adapters/ stays
independent of features/ per the adapter contract.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import httpx

from cassandra.adapters.base import AdapterFetchResult, RawRecord, SourceAdapter
from cassandra.adapters.schedule_mlb import MLB_STATS_API_BASE
from cassandra.db.models.raw import RawPitcherGameLog

FALLBACK_SEASON_MIN_STARTS = 3


class PitcherGameLogsMLBAdapter(SourceAdapter):
    kind = "pitcher_stats"
    source_name = "mlb_stats_api_pitcher_game_logs"
    adapter_version = "0.2.0"
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
            season_records, season_warnings = self._fetch_one_season(
                player_id, slate_date.year, slate_date, fetched_at
            )
            warnings.extend(season_warnings)

            valid_current = sum(1 for r in season_records if r.fields.get("batters_faced") is not None)
            if valid_current < FALLBACK_SEASON_MIN_STARTS:
                prior_records, prior_warnings = self._fetch_one_season(
                    player_id, slate_date.year - 1, slate_date, fetched_at
                )
                warnings.extend(prior_warnings)
                season_records = season_records + prior_records

            records.extend(season_records)

        if not records:
            return AdapterFetchResult(
                records=[],
                fetched_at=fetched_at,
                is_available=False,
                warnings=warnings or ["No prior game log entries found"],
            )
        return AdapterFetchResult(records=records, fetched_at=fetched_at, warnings=warnings)

    def _fetch_one_season(
        self, player_id: int, season: int, slate_date: date, fetched_at: datetime
    ) -> tuple[list[RawRecord], list[str]]:
        try:
            response = self._client.get(
                f"{MLB_STATS_API_BASE}/people/{player_id}/stats",
                params={"stats": "gameLog", "group": "pitching", "season": season},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return [], [f"Game log fetch failed for player {player_id} season {season}: {exc}"]

        stat_groups = payload.get("stats", [])
        splits = stat_groups[0].get("splits", []) if stat_groups else []
        records: list[RawRecord] = []
        for split in splits:
            game_date = split.get("date")
            if not game_date or game_date >= slate_date.isoformat():
                # Only prior starts belong in a pitcher's own history --
                # this isn't the leakage gate itself (ingested_at is,
                # per ADR 0001) but there's no reason to even ingest a
                # same-day-or-later "prior start." A no-op filter for a
                # genuinely prior season, always true for it.
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
        return records, []
