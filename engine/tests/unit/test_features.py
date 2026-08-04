from __future__ import annotations

from datetime import UTC, datetime

from cassandra.db.models.raw import RawPitcherGameLog, RawWeatherObservation
from cassandra.features.builders import (
    build_features,
    compute_recent_k_rate,
    compute_rest_days,
    compute_weather_adjustment,
)
from cassandra.features.expected_bf import compute_expected_bf
from cassandra.pit.snapshot_builder import PitcherSlateEntry

NOW = datetime(2023, 6, 15, 18, 0, tzinfo=UTC)


def _log(stat_date: str, bf: int | None, k: int | None) -> RawPitcherGameLog:
    return RawPitcherGameLog(
        player_mlb_id=1,
        stat_date=datetime.fromisoformat(stat_date),
        batters_faced=bf,
        strikeouts=k,
        pitch_count=90,
        innings_pitched=6.0,
        observed_at=NOW,
        payload={},
    )


# --- expected_bf --------------------------------------------------------


def test_expected_bf_recent_weighted_with_enough_starts():
    logs = [_log("2023-06-10", 24, 7), _log("2023-06-05", 22, 6), _log("2023-05-30", 25, 8)]
    result = compute_expected_bf(logs)
    assert result.tier == "recent_weighted"
    assert result.starts_used == 3
    assert 20 < result.value < 26


def test_expected_bf_season_average_with_few_starts():
    logs = [_log("2023-06-10", 24, 7)]
    result = compute_expected_bf(logs)
    assert result.tier == "season_average"
    assert result.value == 24


def test_expected_bf_league_default_with_no_starts():
    result = compute_expected_bf([])
    assert result.tier == "league_default"
    assert result.starts_used == 0


def test_expected_bf_ignores_logs_missing_batters_faced():
    logs = [_log("2023-06-10", None, 7)]
    result = compute_expected_bf(logs)
    assert result.tier == "league_default"


# --- recent K rate --------------------------------------------------------


def test_k_rate_recent_weighted():
    logs = [_log("2023-06-10", 24, 8), _log("2023-06-05", 22, 6), _log("2023-05-30", 25, 7)]
    result = compute_recent_k_rate(logs)
    assert result.tier == "recent_weighted"
    assert 0.2 < result.value < 0.4


def test_k_rate_league_default_empty():
    result = compute_recent_k_rate([])
    assert result.tier == "league_default"


# --- weather --------------------------------------------------------------


def _weather(temp_f: float | None) -> RawWeatherObservation:
    return RawWeatherObservation(
        venue_id="mlb_venue_2",
        forecast_for=NOW,
        temp_f=temp_f,
        wind_mph=5.0,
        wind_dir="N",
        observed_at=NOW,
        payload={},
    )


def test_weather_adjustment_hot_reduces():
    assert compute_weather_adjustment(_weather(90)) == 0.98


def test_weather_adjustment_cold_increases():
    assert compute_weather_adjustment(_weather(40)) == 1.02


def test_weather_adjustment_moderate_neutral():
    assert compute_weather_adjustment(_weather(70)) == 1.00


def test_weather_adjustment_none_is_neutral():
    assert compute_weather_adjustment(None) == 1.00


# --- rest days --------------------------------------------------------------


def test_rest_days_computed_from_most_recent_log():
    logs = [_log("2023-06-10", 24, 7)]
    days = compute_rest_days(logs, NOW)
    assert days == 5


def test_rest_days_none_when_no_logs():
    assert compute_rest_days([], NOW) is None


# --- build_features integration of the above --------------------------------


def test_build_features_produces_full_blob(monkeypatch):
    logs = [_log("2023-06-10", 24, 7), _log("2023-06-05", 22, 6), _log("2023-05-30", 25, 8)]
    entry = PitcherSlateEntry(
        game=None,
        team_mlb_id=141,
        probable=None,
        game_logs=logs,
        park_factor=None,
        weather=_weather(90),
        lines=[],
        quality_findings=[],
    )
    features = build_features(entry, NOW)
    assert features["expected_bf_tier"] == "recent_weighted"
    assert features["recent_k_rate_tier"] == "recent_weighted"
    assert features["park_k_factor"] == 1.00
    assert features["park_factor_available"] is False
    assert features["weather_adjustment"] == 0.98
    assert features["weather_available"] is True
    assert features["rest_days"] == 5
    assert features["umpire_available"] is False
    assert features["role_stability_flag"] is False
    assert features["opponent_adjustment"] == 1.00
