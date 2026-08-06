"""MLB live lineup adapter -- feeds `raw_lineups`, the pregame batting-
order data the `LINEUP_UNCONFIRMED` reason code is meant to check
against (declared in decision/reason_codes.py's vocabulary since Phase 1
but never wired to a real source until now).

Needs specific game IDs, passed via `fetch(..., mlb_game_pks=[...])` --
same reason as `FinalBoxScoresMLBAdapter`: a single (slate_date, as_of)
pair can't express "which games." Uses the same live-feed endpoint that
adapter and `historical/backfill.py`'s lineup parsing both use
(`liveData.boxscore.teams.{home,away}.battingOrder`/`.players`) -- MLB
typically posts the real lineup roughly 1-3 hours before first pitch, so
an empty `battingOrder` well before game time is the normal pregame
state, not a fetch failure (mirrors `FinalBoxScoresMLBAdapter`'s
`pending` handling for a game that hasn't reached `Final` yet).

One `raw_lineups` row per team per game (not per player): `batting_order`
is a JSONB blob of `{"slot": player_mlb_id}` pairs, so a snapshot/feature
reader gets the whole team's order in one row rather than needing to
group 9 separate rows back together.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import httpx

from cassandra.adapters.base import AdapterFetchResult, RawRecord, SourceAdapter
from cassandra.db.models.raw import RawLineup

LIVE_FEED_BASE = "https://statsapi.mlb.com/api/v1.1"


class LineupMLBAdapter(SourceAdapter):
    kind = "lineup"
    source_name = "mlb_stats_api_lineups"
    adapter_version = "0.1.0"
    raw_model = RawLineup

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
                warnings=["No mlb_game_pks supplied -- nothing to fetch lineups for"],
            )

        records: list[RawRecord] = []
        warnings: list[str] = []
        had_fetch_error = False
        any_lineup_posted = False
        for game_pk in mlb_game_pks:
            try:
                response = self._client.get(f"{LIVE_FEED_BASE}/game/{game_pk}/feed/live")
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                warnings.append(f"Live feed fetch failed for game {game_pk}: {exc}")
                had_fetch_error = True
                continue

            teams_block = payload.get("liveData", {}).get("boxscore", {}).get("teams", {})
            game_data_teams = payload.get("gameData", {}).get("teams", {})
            for side in ("home", "away"):
                team_mlb_id = game_data_teams.get(side, {}).get("id")
                if team_mlb_id is None:
                    continue
                batting_order = teams_block.get(side, {}).get("battingOrder") or []
                if not batting_order:
                    # Normal pregame state well before first pitch --
                    # MLB hasn't posted this team's lineup yet, not a
                    # fetch problem. Same "absence is a first-class
                    # outcome" contract as ProbablePitchersMLBAdapter's
                    # TBD-entry skip. Warned per-side (not just once per
                    # game) so an operator can see specifically which
                    # team is still unposted when the other side already
                    # is.
                    warnings.append(f"No lineup posted yet for game {game_pk} ({side})")
                    continue
                any_lineup_posted = True
                players = teams_block.get(side, {}).get("players", {})
                slots: dict[str, int] = {}
                for pid in batting_order:
                    player_entry = players.get(f"ID{pid}")
                    if player_entry is None:
                        continue
                    slot = player_entry.get("battingOrder")
                    if slot is not None:
                        slots[slot] = pid
                records.append(
                    RawRecord(
                        fields={
                            "mlb_game_pk": game_pk,
                            "team_mlb_id": team_mlb_id,
                            "batting_order": {"order": batting_order, "slots": slots},
                            # A non-empty battingOrder IS MLB's official
                            # posted lineup for this hydration level --
                            # same reasoning as ProbablePitchersMLBAdapter's
                            # is_confirmed=True for a named probable
                            # pitcher (the best confirmation signal
                            # available; a real late swap is caught by a
                            # later, higher-observed_at row superseding
                            # this one via pit/asof.py, not by a separate
                            # flag).
                            "is_confirmed": True,
                        },
                        observed_at=fetched_at,
                        payload={"battingOrder": batting_order, "team_mlb_id": team_mlb_id},
                    )
                )

        if not records:
            pending = not had_fetch_error and not any_lineup_posted
            return AdapterFetchResult(
                records=[],
                fetched_at=fetched_at,
                is_available=False,
                warnings=warnings or ["No lineups found"],
                unavailable_reason="pending" if pending else None,
            )
        return AdapterFetchResult(records=records, fetched_at=fetched_at, warnings=warnings)
