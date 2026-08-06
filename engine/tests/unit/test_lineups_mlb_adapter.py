"""LineupMLBAdapter tests -- synthetic live-feed payloads matching the
real MLB Stats API shape (same shape historical/backfill.py's own lineup
parsing already relies on and tests via inline construction, not a
separate saved-fixture file, since the shape itself is already
well-established elsewhere in this codebase)."""

from __future__ import annotations

from datetime import date

import httpx
import respx

from cassandra.adapters.lineups_mlb import LIVE_FEED_BASE, LineupMLBAdapter

SLATE_DATE = date(2026, 8, 5)
GAME_PK = 900050001


def _feed_payload(*, home_batting_order: list[int], away_batting_order: list[int]) -> dict:
    def _players(batting_order: list[int]) -> dict:
        return {
            f"ID{pid}": {"person": {"id": pid}, "battingOrder": str(100 + i * 100)}
            for i, pid in enumerate(batting_order)
        }

    return {
        "gamePk": GAME_PK,
        "gameData": {
            "teams": {
                "home": {"id": 110},
                "away": {"id": 111},
            },
        },
        "liveData": {
            "boxscore": {
                "teams": {
                    "home": {"battingOrder": home_batting_order, "players": _players(home_batting_order)},
                    "away": {"battingOrder": away_batting_order, "players": _players(away_batting_order)},
                }
            }
        },
    }


@respx.mock
def test_both_lineups_posted_produces_two_records():
    respx.get(f"{LIVE_FEED_BASE}/game/{GAME_PK}/feed/live").mock(
        return_value=httpx.Response(
            200,
            json=_feed_payload(
                home_batting_order=[1, 2, 3, 4, 5, 6, 7, 8, 9],
                away_batting_order=[11, 12, 13, 14, 15, 16, 17, 18, 19],
            ),
        )
    )

    result = LineupMLBAdapter(http_client=httpx.Client()).fetch(slate_date=SLATE_DATE, mlb_game_pks=[GAME_PK])

    assert result.is_available
    assert len(result.records) == 2
    home = next(r for r in result.records if r.fields["team_mlb_id"] == 110)
    assert home.fields["mlb_game_pk"] == GAME_PK
    assert home.fields["is_confirmed"] is True
    assert home.fields["batting_order"]["order"] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert home.fields["batting_order"]["slots"]["100"] == 1


@respx.mock
def test_no_lineup_posted_yet_is_pending_not_a_failure():
    respx.get(f"{LIVE_FEED_BASE}/game/{GAME_PK}/feed/live").mock(
        return_value=httpx.Response(200, json=_feed_payload(home_batting_order=[], away_batting_order=[]))
    )

    result = LineupMLBAdapter(http_client=httpx.Client()).fetch(slate_date=SLATE_DATE, mlb_game_pks=[GAME_PK])

    assert result.is_available is False
    assert result.records == []
    assert result.unavailable_reason == "pending"


@respx.mock
def test_one_side_posted_one_not_returns_the_posted_side_only():
    respx.get(f"{LIVE_FEED_BASE}/game/{GAME_PK}/feed/live").mock(
        return_value=httpx.Response(
            200,
            json=_feed_payload(
                home_batting_order=[1, 2, 3, 4, 5, 6, 7, 8, 9],
                away_batting_order=[],
            ),
        )
    )

    result = LineupMLBAdapter(http_client=httpx.Client()).fetch(slate_date=SLATE_DATE, mlb_game_pks=[GAME_PK])

    assert result.is_available
    assert len(result.records) == 1
    assert result.records[0].fields["team_mlb_id"] == 110
    assert any("No lineup posted yet" in w for w in result.warnings)


def test_no_game_pks_supplied_is_unavailable():
    result = LineupMLBAdapter(http_client=httpx.Client()).fetch(slate_date=SLATE_DATE, mlb_game_pks=[])
    assert result.is_available is False
    assert result.records == []


@respx.mock
def test_fetch_error_for_one_game_does_not_block_another():
    other_game_pk = GAME_PK + 1
    respx.get(f"{LIVE_FEED_BASE}/game/{GAME_PK}/feed/live").mock(return_value=httpx.Response(500))
    respx.get(f"{LIVE_FEED_BASE}/game/{other_game_pk}/feed/live").mock(
        return_value=httpx.Response(
            200,
            json=_feed_payload(
                home_batting_order=[1, 2, 3, 4, 5, 6, 7, 8, 9],
                away_batting_order=[11, 12, 13, 14, 15, 16, 17, 18, 19],
            ),
        )
    )

    result = LineupMLBAdapter(http_client=httpx.Client()).fetch(
        slate_date=SLATE_DATE, mlb_game_pks=[GAME_PK, other_game_pk]
    )

    assert result.is_available
    assert len(result.records) == 2
    assert any("Live feed fetch failed" in w for w in result.warnings)
