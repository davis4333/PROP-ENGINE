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


@respx.mock
def test_prefers_draftkings_over_other_bookmakers():
    # Real fixture has FanDuel first, then Bovada, neither DraftKings --
    # confirms plain list order (first listed wins) as the baseline...
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
    assert result.records[0].payload["bookmaker"] == "fanduel"


@respx.mock
def test_prefers_draftkings_when_listed_after_other_bookmakers():
    # ...and this confirms DraftKings is picked even when it's NOT first
    # in the API's own list order -- the actual point of the preference.
    _mock_events()
    respx.get(f"{API_BASE}/events/{ORIOLES_ANGELS_EVENT_ID}/odds").mock(
        return_value=httpx.Response(200, json=_load("event_odds_no_props_yet.json"))
    )
    multi_bookmaker_detail = {
        "id": YANKEES_CARDINALS_EVENT_ID,
        "commence_time": "2026-08-05T23:06:00Z",
        "home_team": "New York Yankees",
        "away_team": "St. Louis Cardinals",
        "bookmakers": [
            {
                "key": "fanduel",
                "title": "FanDuel",
                "markets": [
                    {
                        "key": "pitcher_strikeouts",
                        "outcomes": [
                            {"name": "Over", "description": "Andre Pallante", "price": 118, "point": 4.5},
                            {"name": "Under", "description": "Andre Pallante", "price": -150, "point": 4.5},
                        ],
                    }
                ],
            },
            {
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [
                    {
                        "key": "pitcher_strikeouts",
                        "outcomes": [
                            {"name": "Over", "description": "Andre Pallante", "price": 105, "point": 5.5},
                            {"name": "Under", "description": "Andre Pallante", "price": -135, "point": 5.5},
                        ],
                    }
                ],
            },
        ],
    }
    respx.get(f"{API_BASE}/events/{YANKEES_CARDINALS_EVENT_ID}/odds").mock(
        return_value=httpx.Response(200, json=multi_bookmaker_detail)
    )
    probables = [{"player_mlb_id": 111, "mlb_game_pk": 999888, "full_name": "Andre Pallante"}]

    result = LinesOddsApiAdapter(api_key="test-key", http_client=httpx.Client()).fetch(
        slate_date=SLATE_DATE, probables=probables
    )

    assert len(result.records) == 1
    record = result.records[0]
    assert record.payload["bookmaker"] == "draftkings"
    assert float(record.fields["line"]) == 5.5


@respx.mock
def test_low_quota_produces_a_warning():
    respx.get(EVENTS_URL).mock(
        return_value=httpx.Response(
            200, json=_load("events_2026-08-05_small.json"), headers={"x-requests-remaining": "5"}
        )
    )
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

    assert result.is_available  # low quota is a warning, not an outage
    assert any("quota low" in w.lower() for w in result.warnings)


@respx.mock
def test_healthy_quota_produces_no_warning():
    respx.get(EVENTS_URL).mock(
        return_value=httpx.Response(
            200, json=_load("events_2026-08-05_small.json"), headers={"x-requests-remaining": "450"}
        )
    )
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

    assert not any("quota" in w.lower() for w in result.warnings)


@respx.mock
def test_same_name_collision_is_never_attached_to_either_player():
    # Regression for a real bug found by an adversarial point-in-time
    # audit: two different confirmed starters sharing an exact full_name
    # previously let the second one silently overwrite the first in a
    # plain dict, so a real line could get attached to the WRONG
    # player_mlb_id/mlb_game_pk with no warning at all. A bare vendor
    # name string can't disambiguate them, so neither should get the line.
    _mock_events()
    respx.get(f"{API_BASE}/events/{ORIOLES_ANGELS_EVENT_ID}/odds").mock(
        return_value=httpx.Response(200, json=_load("event_odds_no_props_yet.json"))
    )
    respx.get(f"{API_BASE}/events/{YANKEES_CARDINALS_EVENT_ID}/odds").mock(
        return_value=httpx.Response(200, json=_load("event_odds_with_props.json"))
    )
    probables = [
        {"player_mlb_id": 111, "mlb_game_pk": 999888, "full_name": "Andre Pallante"},
        {"player_mlb_id": 999, "mlb_game_pk": 111222, "full_name": "Andre Pallante"},  # collision
    ]

    result = LinesOddsApiAdapter(api_key="test-key", http_client=httpx.Client()).fetch(
        slate_date=SLATE_DATE, probables=probables
    )

    assert not any(r.fields["player_mlb_id"] in (111, 999) for r in result.records)
    assert any("Ambiguous" in w and "Andre Pallante" in w for w in result.warnings)


@respx.mock
def test_events_http_error_never_leaks_the_api_key_into_a_warning():
    # Regression for a real finding from a security review: httpx.HTTPStatusError's
    # own str() embeds the full request URL, including the apiKey query
    # param -- warnings must never be built from str(exc) directly, since
    # they flow into the audit_events table, admin API responses, and
    # CLI/deploy logs.
    respx.get(EVENTS_URL).mock(return_value=httpx.Response(401, json={"message": "Invalid API key"}))
    probables = [{"player_mlb_id": 111, "mlb_game_pk": 999888, "full_name": "Andre Pallante"}]
    fake_key_value_for_this_test_only = "test-key"

    result = LinesOddsApiAdapter(
        api_key=fake_key_value_for_this_test_only, http_client=httpx.Client()
    ).fetch(slate_date=SLATE_DATE, probables=probables)

    assert result.is_available is False
    assert not any(fake_key_value_for_this_test_only in w for w in result.warnings)
    assert not any("apiKey" in w for w in result.warnings)
    assert any("401" in w for w in result.warnings)
