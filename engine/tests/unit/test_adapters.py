"""Adapter tests -- real parsing logic exercised against real MLB Stats API
/ Open-Meteo responses saved as fixtures (see tests/fixtures/mlb_api/),
mocked via respx rather than live network calls, so tests are
deterministic and offline-capable per the adapter-testing convention in
docs/DEVELOPMENT.md.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
import respx

from cassandra.adapters.final_box_scores_mlb import LIVE_FEED_BASE, FinalBoxScoresMLBAdapter
from cassandra.adapters.lines_manual import LinesManualAdapter
from cassandra.adapters.park_factors_static import NEUTRAL_K_FACTOR, ParkFactorsStaticAdapter
from cassandra.adapters.pitcher_game_logs_mlb import PitcherGameLogsMLBAdapter
from cassandra.adapters.probable_pitchers_mlb import ProbablePitchersMLBAdapter
from cassandra.adapters.schedule_mlb import MLB_STATS_API_BASE, ScheduleMLBAdapter
from cassandra.adapters.umpire_stub import UmpireStubAdapter
from cassandra.adapters.weather_openmeteo import ARCHIVE_URL, WeatherOpenMeteoAdapter
from cassandra.identity_ids import mlb_venue_id

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "mlb_api"
SLATE_DATE = date(2023, 6, 15)


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


# --- schedule -----------------------------------------------------------


@respx.mock
def test_schedule_adapter_parses_real_response():
    respx.get(f"{MLB_STATS_API_BASE}/schedule").mock(
        return_value=httpx.Response(200, json=_load("schedule_2023-06-15.json"))
    )
    result = ScheduleMLBAdapter(http_client=httpx.Client()).fetch(slate_date=SLATE_DATE)
    assert result.is_available
    assert len(result.records) >= 1
    first = result.records[0]
    assert first.fields["mlb_game_pk"] == 717753
    assert first.payload["teams"]["home"]["team"]["id"] == 110


@respx.mock
def test_schedule_adapter_handles_http_failure_without_raising():
    respx.get(f"{MLB_STATS_API_BASE}/schedule").mock(return_value=httpx.Response(500))
    result = ScheduleMLBAdapter(http_client=httpx.Client()).fetch(slate_date=SLATE_DATE)
    assert result.is_available is False
    assert result.records == []
    assert result.warnings


@respx.mock
def test_schedule_adapter_handles_empty_slate():
    respx.get(f"{MLB_STATS_API_BASE}/schedule").mock(return_value=httpx.Response(200, json={"dates": []}))
    result = ScheduleMLBAdapter(http_client=httpx.Client()).fetch(slate_date=SLATE_DATE)
    assert result.is_available is False
    assert result.records == []


# --- probable pitchers ----------------------------------------------------


@respx.mock
def test_probable_pitchers_adapter_parses_real_response():
    respx.get(f"{MLB_STATS_API_BASE}/schedule").mock(
        return_value=httpx.Response(200, json=_load("schedule_2023-06-15.json"))
    )
    result = ProbablePitchersMLBAdapter(http_client=httpx.Client()).fetch(slate_date=SLATE_DATE)
    assert result.is_available
    kikuchi = next(r for r in result.records if r.fields["player_mlb_id"] == 579328)
    assert kikuchi.fields["mlb_game_pk"] == 717753
    assert kikuchi.fields["team_mlb_id"] == 141
    assert kikuchi.fields["is_confirmed"] is True


@respx.mock
def test_probable_pitchers_adapter_confirms_a_genuinely_pregame_listing():
    # Regression for a real, severe bug: is_confirmed used to compare the
    # GAME's status.abstractGameState against "Preview", which is true
    # for every game that hasn't started yet -- meaning a normal pregame
    # probable-pitcher listing (the overwhelming majority of real-world
    # calls, since this adapter runs pregame) was always marked
    # unconfirmed. That fed straight into decision/engine.py's
    # QUALITY_RISK_CODES and force every pregame projection to
    # NO_PLAY/UNCERTAIN regardless of edge -- confirmed live, this
    # silently suppressed every QUALIFIED pick since this platform went
    # live. A named, numeric-id probable pitcher listing IS MLB's
    # official pregame starter signal and must be usable before the game
    # starts, not just after.
    pregame_schedule = {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": 999888,
                        "status": {"abstractGameState": "Preview", "detailedState": "Scheduled"},
                        "teams": {
                            "home": {
                                "team": {"id": 110},
                                "probablePitcher": {"id": 669330, "fullName": "Tyler Wells"},
                            },
                            "away": {
                                "team": {"id": 141},
                                "probablePitcher": {"id": 579328, "fullName": "Yusei Kikuchi"},
                            },
                        },
                    }
                ]
            }
        ]
    }
    respx.get(f"{MLB_STATS_API_BASE}/schedule").mock(return_value=httpx.Response(200, json=pregame_schedule))

    result = ProbablePitchersMLBAdapter(http_client=httpx.Client()).fetch(slate_date=SLATE_DATE)

    assert result.is_available
    assert len(result.records) == 2
    assert all(r.fields["is_confirmed"] is True for r in result.records)


# --- pitcher game logs -----------------------------------------------------


@respx.mock
def test_pitcher_game_logs_adapter_parses_real_response_and_filters_future_games():
    respx.get(f"{MLB_STATS_API_BASE}/people/579328/stats").mock(
        return_value=httpx.Response(200, json=_load("gamelog_579328_2023.json"))
    )
    result = PitcherGameLogsMLBAdapter(http_client=httpx.Client()).fetch(
        slate_date=SLATE_DATE, player_mlb_ids=[579328]
    )
    assert result.is_available
    assert len(result.records) >= 1
    for r in result.records:
        assert r.fields["stat_date"] < SLATE_DATE.isoformat()
        assert r.fields["player_mlb_id"] == 579328
    first = result.records[0]
    assert first.fields["strikeouts"] is not None
    assert first.fields["batters_faced"] is not None


def test_pitcher_game_logs_adapter_no_player_ids_is_unavailable_not_raise():
    result = PitcherGameLogsMLBAdapter(http_client=httpx.Client()).fetch(slate_date=SLATE_DATE)
    assert result.is_available is False
    assert result.records == []


def _thin_current_season_gamelog() -> dict:
    # Only one valid start this season -- below FALLBACK_SEASON_MIN_STARTS
    # (3), the scenario that should trigger a prior-season fallback fetch
    # (a rookie call-up, a rehab return, or genuinely early season).
    return {
        "stats": [
            {
                "splits": [
                    {
                        "date": "2023-06-10",
                        "game": {"gamePk": 900001},
                        "stat": {"battersFaced": 24, "strikeOuts": 7, "numberOfPitches": 90},
                    }
                ]
            }
        ]
    }


def _prior_season_gamelog() -> dict:
    return {
        "stats": [
            {
                "splits": [
                    {
                        "date": "2022-09-20",
                        "game": {"gamePk": 800001},
                        "stat": {"battersFaced": 22, "strikeOuts": 6, "numberOfPitches": 88},
                    },
                    {
                        "date": "2022-09-14",
                        "game": {"gamePk": 800002},
                        "stat": {"battersFaced": 21, "strikeOuts": 5, "numberOfPitches": 85},
                    },
                ]
            }
        ]
    }


@respx.mock
def test_pitcher_game_logs_adapter_falls_back_to_prior_season_when_current_season_is_thin():
    current = respx.get(f"{MLB_STATS_API_BASE}/people/123456/stats", params={"season": "2023"}).mock(
        return_value=httpx.Response(200, json=_thin_current_season_gamelog())
    )
    prior = respx.get(f"{MLB_STATS_API_BASE}/people/123456/stats", params={"season": "2022"}).mock(
        return_value=httpx.Response(200, json=_prior_season_gamelog())
    )
    result = PitcherGameLogsMLBAdapter(http_client=httpx.Client()).fetch(
        slate_date=SLATE_DATE, player_mlb_ids=[123456]
    )
    assert current.called
    assert prior.called
    assert result.is_available
    stat_dates = {r.fields["stat_date"] for r in result.records}
    assert stat_dates == {"2023-06-10", "2022-09-20", "2022-09-14"}


@respx.mock
def test_pitcher_game_logs_adapter_skips_fallback_when_current_season_has_enough_starts():
    current = respx.get(f"{MLB_STATS_API_BASE}/people/579328/stats", params={"season": "2023"}).mock(
        return_value=httpx.Response(200, json=_load("gamelog_579328_2023.json"))
    )
    prior = respx.get(f"{MLB_STATS_API_BASE}/people/579328/stats", params={"season": "2022"}).mock(
        return_value=httpx.Response(200, json=_prior_season_gamelog())
    )
    result = PitcherGameLogsMLBAdapter(http_client=httpx.Client()).fetch(
        slate_date=SLATE_DATE, player_mlb_ids=[579328]
    )
    assert current.called
    assert not prior.called
    assert result.is_available
    assert all(r.fields["stat_date"] < "2023-06-15" for r in result.records)
    assert all("2022" not in r.fields["stat_date"] for r in result.records)


# --- weather -----------------------------------------------------------------


@respx.mock
def test_weather_adapter_parses_real_archive_response():
    respx.get(ARCHIVE_URL).mock(return_value=httpx.Response(200, json=_load("weather_archive_camden.json")))
    result = WeatherOpenMeteoAdapter(http_client=httpx.Client()).fetch(
        slate_date=SLATE_DATE,
        venues=[
            {
                "venue_id": 2,
                "lat": 39.284,
                "lon": -76.6217,
                "game_time_utc": datetime(2023, 6, 15, 17, 5, tzinfo=UTC),
            }
        ],
    )
    assert result.is_available
    rec = result.records[0]
    assert rec.fields["venue_id"] == mlb_venue_id(2)
    assert rec.fields["temp_f"] is not None
    assert rec.fields["wind_dir"] in {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}


def test_weather_adapter_no_venues_is_unavailable_not_raise():
    result = WeatherOpenMeteoAdapter(http_client=httpx.Client()).fetch(slate_date=SLATE_DATE)
    assert result.is_available is False


# --- park factors (no HTTP) -------------------------------------------------


def test_park_factors_static_known_venue():
    result = ParkFactorsStaticAdapter().fetch(slate_date=SLATE_DATE, venue_ids=[2])
    assert result.is_available
    rec = result.records[0]
    assert rec.fields["venue_id"] == mlb_venue_id(2)
    assert rec.fields["k_factor"] == 1.00
    assert not result.warnings


def test_park_factors_static_unknown_venue_falls_back_neutral_with_warning():
    result = ParkFactorsStaticAdapter().fetch(slate_date=SLATE_DATE, venue_ids=[999999])
    assert result.is_available
    assert result.records[0].fields["k_factor"] == NEUTRAL_K_FACTOR
    assert result.warnings


# --- umpire stub -------------------------------------------------------------


def test_umpire_stub_always_unavailable_never_raises():
    result = UmpireStubAdapter().fetch(slate_date=SLATE_DATE)
    assert result.is_available is False
    assert result.records == []
    assert result.warnings


# --- lines manual --------------------------------------------------------


@pytest.fixture
def lines_drop_dir(tmp_path: Path) -> Path:
    doc = {
        "slate_date": "2023-06-15",
        "observed_at": "2023-06-15T15:00:00Z",
        "lines": [
            {
                "mlb_game_pk": 717753,
                "player_mlb_id": 579328,
                "market": "pitcher_strikeouts",
                "line": 5.5,
                "over_price": -115,
                "under_price": -105,
                "is_suspended": False,
            }
        ],
    }
    (tmp_path / "demo.json").write_text(json.dumps(doc))
    return tmp_path


def test_lines_manual_reads_matching_drop_file(lines_drop_dir: Path):
    result = LinesManualAdapter(drop_dir=lines_drop_dir).fetch(slate_date=SLATE_DATE)
    assert result.is_available
    rec = result.records[0]
    assert rec.fields["mlb_game_pk"] == 717753
    assert rec.fields["line"] == 5.5
    assert rec.record_hash is not None


def test_lines_manual_no_matching_file_is_unavailable(lines_drop_dir: Path):
    result = LinesManualAdapter(drop_dir=lines_drop_dir).fetch(slate_date=date(2099, 1, 1))
    assert result.is_available is False
    assert result.records == []


def test_lines_manual_missing_drop_dir_is_unavailable(tmp_path: Path):
    result = LinesManualAdapter(drop_dir=tmp_path / "does_not_exist").fetch(slate_date=SLATE_DATE)
    assert result.is_available is False


# --- final box scores ----------------------------------------------------


@respx.mock
def test_final_box_scores_adapter_parses_real_response():
    respx.get(f"{LIVE_FEED_BASE}/game/717753/feed/live").mock(
        return_value=httpx.Response(200, json=_load("game_feed_717753.json"))
    )
    result = FinalBoxScoresMLBAdapter(http_client=httpx.Client()).fetch(
        slate_date=SLATE_DATE, mlb_game_pks=[717753]
    )
    assert result.is_available
    kikuchi = next(r for r in result.records if r.fields["player_mlb_id"] == 579328)
    assert kikuchi.fields["mlb_game_pk"] == 717753
    assert kikuchi.fields["strikeouts_recorded"] == 7
    assert kikuchi.fields["game_status"] == "Final"
    assert kikuchi.fields["pitch_count"] == 94
    # every pitcher in either team's boxscore, not just the one checked above
    assert len(result.records) >= 5


@respx.mock
def test_final_box_scores_adapter_handles_http_failure_without_raising():
    respx.get(f"{LIVE_FEED_BASE}/game/717753/feed/live").mock(return_value=httpx.Response(500))
    result = FinalBoxScoresMLBAdapter(http_client=httpx.Client()).fetch(
        slate_date=SLATE_DATE, mlb_game_pks=[717753]
    )
    assert result.is_available is False
    assert result.records == []
    assert result.warnings


def test_final_box_scores_adapter_no_game_pks_is_unavailable():
    result = FinalBoxScoresMLBAdapter(http_client=httpx.Client()).fetch(slate_date=SLATE_DATE)
    assert result.is_available is False
    assert result.records == []
