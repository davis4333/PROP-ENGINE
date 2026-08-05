"""The Odds API player-props adapter for MLB pitcher strikeouts -- a real,
licensed odds vendor (regulated US sportsbooks: FanDuel, DraftKings,
BetMGM, etc.), standing in for a not-yet-connected Underdog/DFS line feed.
Underdog's own real acquisition method/ToS is still legally unresolved
(see lines_manual.py's docstring and docs/DECISION_LEDGER.csv) -- this is
NOT Underdog's own pick'em lines, it's real sportsbook strikeout totals,
which is a real and legitimate (if different) market. Swapping this
adapter out for a real Underdog one later, or for a different vendor,
only requires changing which adapter ingest_slate() calls -- the output
contract (AdapterFetchResult of RawRecords targeting raw_lines) stays
identical either way.

The Odds API identifies games by its own event id + team names (not MLB's
gamePk) and players by a free-text name string (not an MLB person id), so
this adapter needs already-known probable-pitcher context to resolve
those into our identity scheme -- passed via
`fetch(..., probables=[{"player_mlb_id":..., "full_name":...,
"mlb_game_pk":...}, ...])`. A prop for a name that isn't in that list (a
bench/relief pitcher prop, a name-format mismatch) is silently skipped
with a warning, never guessed at -- matching every other adapter's
"absence is a first-class outcome" contract.

Fetching odds is a per-event, credit-metered call, so events are first
filtered to the slate's date window (same window games_for_slate_date
uses) before requesting their odds -- avoids burning API credits on
games days away from this slate.

Uses whichever bookmaker is listed first for a given player's
pitcher_strikeouts market; cross-book consensus is a future improvement,
not needed for this MVP (see CURRENT_STATE_AUDIT.md's Provisional
section).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx

from cassandra.adapters.base import AdapterFetchResult, RawRecord, SourceAdapter
from cassandra.db.models.raw import RawLine

API_BASE = "https://api.the-odds-api.com/v4/sports/baseball_mlb"
EVENTS_URL = f"{API_BASE}/events"
MARKET = "pitcher_strikeouts"


class LinesOddsApiAdapter(SourceAdapter):
    kind = "lines"
    source_name = "odds_api"
    adapter_version = "0.1.0"
    raw_model = RawLine

    def __init__(self, api_key: str, http_client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = http_client or httpx.Client(timeout=15.0)

    def fetch(self, *, slate_date: date, as_of: datetime | None = None, **kwargs: Any) -> AdapterFetchResult:
        fetched_at = datetime.now(UTC)
        probables: list[dict[str, Any]] = kwargs.get("probables") or []
        if not probables:
            return AdapterFetchResult(
                records=[],
                fetched_at=fetched_at,
                is_available=False,
                warnings=["No confirmed probable pitchers supplied -- nothing to look up props for"],
            )
        by_name: dict[str, dict[str, Any]] = {p["full_name"]: p for p in probables}

        try:
            events_resp = self._client.get(EVENTS_URL, params={"apiKey": self._api_key, "dateFormat": "iso"})
            events_resp.raise_for_status()
            events = events_resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            return AdapterFetchResult(
                records=[],
                fetched_at=fetched_at,
                is_available=False,
                warnings=[f"Could not fetch MLB events: {exc}"],
            )

        window_start = datetime.combine(slate_date, time.min, tzinfo=UTC) - timedelta(days=1)
        window_end = window_start + timedelta(days=3)
        records: list[RawRecord] = []
        warnings: list[str] = []
        matched_names: set[str] = set()

        for event in events:
            event_id = event.get("id")
            commence_raw = event.get("commence_time")
            if not event_id or not commence_raw:
                continue
            try:
                commence_at = datetime.fromisoformat(commence_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if not (window_start <= commence_at < window_end):
                continue

            try:
                odds_resp = self._client.get(
                    f"{API_BASE}/events/{event_id}/odds",
                    params={
                        "apiKey": self._api_key,
                        "regions": "us",
                        "markets": MARKET,
                        "oddsFormat": "american",
                        "dateFormat": "iso",
                    },
                )
                odds_resp.raise_for_status()
                detail = odds_resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                warnings.append(f"Could not fetch odds for event {event_id}: {exc}")
                continue

            records.extend(_records_for_event(detail, event_id, by_name, matched_names, fetched_at))

        unmatched = sorted(set(by_name) - matched_names)
        if unmatched:
            warnings.append(f"No {MARKET} prop found for: {', '.join(unmatched)}")

        if not records:
            return AdapterFetchResult(
                records=[],
                fetched_at=fetched_at,
                is_available=False,
                warnings=warnings or [f"No {MARKET} props found for any confirmed starter"],
            )
        return AdapterFetchResult(records=records, fetched_at=fetched_at, warnings=warnings)


def _records_for_event(
    detail: dict[str, Any],
    event_id: str,
    by_name: dict[str, dict[str, Any]],
    matched_names: set[str],
    fetched_at: datetime,
) -> list[RawRecord]:
    records: list[RawRecord] = []
    for bookmaker in detail.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market.get("key") != MARKET:
                continue
            by_player: dict[str, dict[str, float | None]] = {}
            for outcome in market.get("outcomes", []):
                player_name = outcome.get("description")
                side = outcome.get("name")
                if player_name is None or side not in ("Over", "Under"):
                    continue
                slot = by_player.setdefault(
                    player_name, {"line": None, "over_price": None, "under_price": None}
                )
                slot["line"] = outcome.get("point")
                if side == "Over":
                    slot["over_price"] = outcome.get("price")
                else:
                    slot["under_price"] = outcome.get("price")

            for player_name, sides in by_player.items():
                if player_name in matched_names or sides["line"] is None:
                    continue
                probable = by_name.get(player_name)
                if probable is None:
                    continue  # not one of today's confirmed starters -- skip silently, no guess
                matched_names.add(player_name)
                payload = {
                    "bookmaker": bookmaker.get("key"),
                    "event_id": event_id,
                    "player_name": player_name,
                    **sides,
                }
                records.append(
                    RawRecord(
                        fields={
                            "mlb_game_pk": probable["mlb_game_pk"],
                            "player_mlb_id": probable["player_mlb_id"],
                            "market": MARKET,
                            "line": sides["line"],
                            "over_price": sides["over_price"],
                            "under_price": sides["under_price"],
                            "is_suspended": False,
                        },
                        observed_at=fetched_at,
                        payload=payload,
                    )
                )
    return records
