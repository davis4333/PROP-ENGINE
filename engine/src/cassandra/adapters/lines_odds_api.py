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
"absence is a first-class outcome" contract. If two confirmed starters on
the same slate happen to share an identical full_name (a real, if rare,
collision -- e.g. two different "Luis Garcia"s), a bare name match can't
tell them apart; a found line for that name is deliberately NOT attached
to either one, with a visible warning, rather than silently guessing --
found and fixed after a live adversarial point-in-time/correctness audit
traced exactly this failure mode.

Fetching odds is a per-event, credit-metered call, so events are first
filtered to the slate's date window (same window games_for_slate_date
uses) before requesting their odds -- avoids burning API credits on
games days away from this slate.

Prefers DraftKings when it has posted a given player's market, falling
back to whichever other bookmaker has it; cross-book consensus is a
future improvement, not needed for this MVP (see
CURRENT_STATE_AUDIT.md's Provisional section).

The Odds API's free tier is quota-metered (500 requests/month) and
returns the remaining balance on every response via the
`x-requests-remaining` header -- logged at INFO on every fetch, and
surfaced as a real warning (not just a log line) once it drops below
`LOW_QUOTA_WARNING_THRESHOLD`, so a long-running deployment doesn't
silently run out mid-slate.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx

from cassandra.adapters.base import AdapterFetchResult, RawRecord, SourceAdapter
from cassandra.db.models.raw import RawLine

logger = logging.getLogger(__name__)

API_BASE = "https://api.the-odds-api.com/v4/sports/baseball_mlb"
EVENTS_URL = f"{API_BASE}/events"
MARKET = "pitcher_strikeouts"
PREFERRED_BOOKMAKER = "draftkings"
LOW_QUOTA_WARNING_THRESHOLD = 20


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

        by_name: dict[str, list[dict[str, Any]]] = {}
        for p in probables:
            by_name.setdefault(p["full_name"], []).append(p)
        # Two different confirmed starters sharing an exact full_name is
        # rare but real (verified as a genuine, reproducible bug in an
        # earlier version of this adapter, which silently attached a real
        # line to the wrong player_mlb_id/mlb_game_pk on this exact
        # collision) -- a bare vendor name string alone can't disambiguate
        # them, so any line found for an ambiguous name is deliberately
        # dropped rather than guessed at.
        ambiguous_names = {name for name, group in by_name.items() if len(group) > 1}

        warnings: list[str] = []
        for name in sorted(ambiguous_names):
            warnings.append(
                f"Ambiguous: {len(by_name[name])} confirmed starters today are named "
                f"'{name}' -- cannot safely attach a line to either from a bare name "
                "match alone, so none was attached"
            )

        try:
            events_resp = self._client.get(EVENTS_URL, params={"apiKey": self._api_key, "dateFormat": "iso"})
            events_resp.raise_for_status()
            events = events_resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            return AdapterFetchResult(
                records=[],
                fetched_at=fetched_at,
                is_available=False,
                warnings=[*warnings, f"Could not fetch MLB events: {_safe_fetch_error(exc)}"],
            )
        _check_quota(events_resp, warnings)

        window_start = datetime.combine(slate_date, time.min, tzinfo=UTC) - timedelta(days=1)
        window_end = window_start + timedelta(days=3)
        records: list[RawRecord] = []
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
                warnings.append(f"Could not fetch odds for event {event_id}: {_safe_fetch_error(exc)}")
                continue
            _check_quota(odds_resp, warnings)

            records.extend(
                _records_for_event(detail, event_id, by_name, ambiguous_names, matched_names, fetched_at)
            )

        unmatched = sorted(set(by_name) - matched_names - ambiguous_names)
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
    by_name: dict[str, list[dict[str, Any]]],
    ambiguous_names: set[str],
    matched_names: set[str],
    fetched_at: datetime,
) -> list[RawRecord]:
    records: list[RawRecord] = []
    for bookmaker in _ordered_bookmakers(detail.get("bookmakers", [])):
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
                if player_name in matched_names or player_name in ambiguous_names or sides["line"] is None:
                    continue
                candidates = by_name.get(player_name)
                if not candidates:
                    continue  # not one of today's confirmed starters -- skip silently, no guess
                probable = candidates[0]  # len == 1 here: ambiguous (len > 1) names are filtered above
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


def _ordered_bookmakers(bookmakers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """DraftKings first (when present), everything else after in whatever
    order the API returned -- the caller keeps only the first bookmaker
    seen for a given player, so this ordering is what "prefers DraftKings,
    falls back to any other" actually means in practice."""
    preferred = [b for b in bookmakers if b.get("key") == PREFERRED_BOOKMAKER]
    rest = [b for b in bookmakers if b.get("key") != PREFERRED_BOOKMAKER]
    return preferred + rest


def _safe_fetch_error(exc: Exception) -> str:
    """A warning-safe error description that never touches str(exc).

    httpx.HTTPStatusError's __str__ embeds the full request URL,
    including this adapter's apiKey query parameter -- str()-ing it
    directly into a warning would risk leaking the vendor API key into
    AdapterFetchResult.warnings, which flows into the append-only,
    undeletable audit_events table (ingest_service.py), admin API
    responses (GET /api/admin/status, POST .../run), and CLI stdout/
    deploy logs. A real HTTP-error scenario (401 on a bad/rotated key,
    429 on quota exhaustion, a vendor 5xx) is exactly the case this
    exists for -- found during a live security review, not hypothetical.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


def _check_quota(response: httpx.Response, warnings: list[str]) -> None:
    """The Odds API returns remaining monthly-quota balance on every
    response via this header. Always logged (operational visibility);
    only escalated to a real warning near exhaustion, since logging every
    call at warning level would drown out actual problems."""
    remaining_raw = response.headers.get("x-requests-remaining")
    if remaining_raw is None:
        return
    try:
        remaining = int(remaining_raw)
    except ValueError:
        return
    logger.info("Odds API requests remaining this period: %d", remaining)
    if remaining < LOW_QUOTA_WARNING_THRESHOLD:
        warnings.append(f"Odds API quota low: only {remaining} requests remaining this period")
