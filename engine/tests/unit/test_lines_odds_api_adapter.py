"""LinesOddsApiAdapter tests -- real parsing logic exercised against real
The Odds API responses saved as fixtures (see tests/fixtures/odds_api/,
captured against the live API during this build), mocked via respx per
the adapter-testing convention in docs/DEVELOPMENT.md. The events-list
fixture is a real two-entry slice of a real ~30-event response (trimmed
only to keep the number of per-event mocks manageable, not synthesized).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import respx

from cassandra.adapters.lines_odds_api import API_BASE, EVENTS_URL, LinesOddsApiAdapter

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "odds_api"
SLATE_DATE = date(2026, 8, 5)
ORIOLES_ANGELS_EVENT_ID = "fe0d956203b65ef42f68a6d324f8b922"
YANKEES_CARDINALS_EVENT_ID = "2da70aefb8ce542046f6790787c32469"


def _load(name: str) -> dict | list:
    return json.loads((FIXTURES / name).read_text())


def _mock_events() -> None:
    respx.get(EVENTS_URL).mock(return_value=httpx.Response(200, json=_load("events_2026-08-05_small.json")))


@respx.mock
def test_matches_confirmed_probables_and_builds_lines():
    _mock_events()
    respx.get(f"{API_BASE}/events/{ORIOLES_ANGELS_EVENT_ID}/odds").mock(
        return_value=httpx.Response(200, json=_load("event_odds_no_props_yet.json"))
    )
    respx.get(f"{API_BASE}/events/{YANKEES_CARDINALS_EVENT_ID}/odds").mock(
        return_value=httpx.Response(200, json=_load("event_odds_with_props.json"))
    )
    probables = [
        {"player_mlb_id": 111, "mlb_game_pk": 999888, "full_name": "Andre Pallante"},
        {"player_mlb_id": 222, "mlb_game_pk": 999888, "full_name": "Will Warren"},
    ]

    result = LinesOddsApiAdapter(api_key="test-key", http_client=httpx.Client()).fetch(
        slate_date=SLATE_DATE, probables=probables
    )

    assert result.is_available
    assert len(result.records) == 2
    pallante = next(r for r in result.records if r.fields["player_mlb_id"] == 111)
    assert pallante.fields["mlb_game_pk"] == 999888
    assert pallante.fields["market"] == "pitcher_strikeouts"
    assert float(pallante.fields["line"]) == 4.5
    assert pallante.fields["over_price"] == 118
    assert pallante.fields["under_price"] == -150
    assert pallante.payload["bookmaker"] == "fanduel"
    warren = next(r for r in result.records if r.fields["player_mlb_id"] == 222)
    assert float(warren.fields["line"]) == 4.5
    assert warren.fields["over_price"] == 114


@respx.mock
def test_skips_a_prop_for_a_player_not_in_the_confirmed_probables_list():
    # Will Warren has a real prop in the fixture but isn't one of today's
    # confirmed starters per this test's probables -- must be silently
    # dropped (no guessing at an unmatched player_mlb_id), not an error.
    _mock_events()
    respx.get(f"{API_BASE}/events/{ORIOLES_ANGELS_EVENT_ID}/odds").mock(
        return_value=httpx.Response(200, json=_load("event_odds_no_props_yet.json"))
    )
    respx.get(f"{API_BASE}/events/{YANKEES_CARDINALS_EVENT_ID}/odds").mock(
        return_value=httpx.Response(200, json=_load("event_odds_with_props.json"))
    )
    probables = [{"player_mlb_id": 111, "mlb_game_pk": 999888, "full_name": "Andre Pallante"}]

    result = LinesOddsApiAdapter(api_key="test-key", http_client=httpx.Client()).fetch(
        slate_date=SLATE_DATE, probables=probables
    )

    assert result.is_available
    assert len(result.records) == 1
    assert result.records[0].fields["player_mlb_id"] == 111


@respx.mock
def test_unmatched_confirmed_starter_produces_a_warning_not_a_crash():
    _mock_events()
    respx.get(f"{API_BASE}/events/{ORIOLES_ANGELS_EVENT_ID}/odds").mock(
        return_value=httpx.Response(200, json=_load("event_odds_no_props_yet.json"))
    )
    respx.get(f"{API_BASE}/events/{YANKEES_CARDINALS_EVENT_ID}/odds").mock(
        return_value=httpx.Response(200, json=_load("event_odds_with_props.json"))
    )
    probables = [{"player_mlb_id": 333, "mlb_game_pk": 999888, "full_name": "Nobody Confirmed"}]

    result = LinesOddsApiAdapter(api_key="test-key", http_client=httpx.Client()).fetch(
        slate_date=SLATE_DATE, probables=probables
    )

    assert result.is_available is False
    assert result.records == []
    assert any("Nobody Confirmed" in w for w in result.warnings)


def test_no_probables_supplied_is_unavailable_not_raise():
    result = LinesOddsApiAdapter(api_key="test-key", http_client=httpx.Client()).fetch(slate_date=SLATE_DATE)
    assert result.is_available is False
    assert result.records == []


@respx.mock
def test_events_outside_the_slate_window_are_never_requested():
    # No per-event odds routes are mocked at all -- if the adapter called
    # one anyway, respx would raise (unmocked request), which is exactly
    # the failure mode this test is checking for.
    _mock_events()
    probables = [{"player_mlb_id": 111, "mlb_game_pk": 999888, "full_name": "Andre Pallante"}]

    result = LinesOddsApiAdapter(api_key="test-key", http_client=httpx.Client()).fetch(
        slate_date=date(2023, 6, 15), probables=probables
    )

    assert result.is_available is False
    assert result.records == []


@respx.mock
def test_events_fetch_failure_is_unavailable_not_raise():
    respx.get(EVENTS_URL).mock(return_value=httpx.Response(500))
    probables = [{"player_mlb_id": 111, "mlb_game_pk": 999888, "full_name": "Andre Pallante"}]

    result = LinesOddsApiAdapter(api_key="test-key", http_client=httpx.Client()).fetch(
        slate_date=SLATE_DATE, probables=probables
    )

    assert result.is_available is False
    assert result.records == []
    assert result.warnings
