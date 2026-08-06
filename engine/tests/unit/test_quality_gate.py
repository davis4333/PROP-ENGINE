from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cassandra.db.models.raw import RawLine, RawLineup, RawProbablePitcher
from cassandra.ingestion.quality_gate import (
    check_data_stale,
    check_line_available,
    check_line_conflict,
    check_lineup_confirmed,
    check_starter_confirmed,
)

NOW = datetime(2023, 6, 15, 18, 0, tzinfo=UTC)


def _line(line: float, observed_at: datetime, is_suspended: bool = False) -> RawLine:
    return RawLine(
        mlb_game_pk=1,
        player_mlb_id=1,
        market="pitcher_strikeouts",
        line=line,
        is_suspended=is_suspended,
        observed_at=observed_at,
        payload={},
    )


def test_starter_confirmed_missing_is_fail():
    finding = check_starter_confirmed(None)
    assert finding is not None
    assert finding.reason_code == "DATA_MISSING"
    assert finding.status == "fail"


def test_starter_confirmed_unconfirmed_is_warn():
    probable = RawProbablePitcher(
        mlb_game_pk=1, player_mlb_id=1, is_confirmed=False, observed_at=NOW, payload={}
    )
    finding = check_starter_confirmed(probable)
    assert finding is not None
    assert finding.reason_code == "STARTER_UNCONFIRMED"
    assert finding.status == "warn"


def test_starter_confirmed_clean_is_none():
    probable = RawProbablePitcher(
        mlb_game_pk=1, player_mlb_id=1, is_confirmed=True, observed_at=NOW, payload={}
    )
    assert check_starter_confirmed(probable) is None


def test_lineup_confirmed_missing_is_warn():
    finding = check_lineup_confirmed(None)
    assert finding is not None
    assert finding.reason_code == "LINEUP_UNCONFIRMED"
    assert finding.status == "warn"


def test_lineup_confirmed_present_is_none():
    lineup = RawLineup(
        mlb_game_pk=1,
        team_mlb_id=110,
        batting_order={"order": [1, 2, 3], "slots": {}},
        is_confirmed=True,
        observed_at=NOW,
        payload={},
    )
    assert check_lineup_confirmed(lineup) is None


def test_line_available_empty_is_fail():
    finding = check_line_available([])
    assert finding is not None
    assert finding.reason_code == "MARKET_CONTEXT_INCOMPLETE"
    assert finding.status == "fail"


def test_line_available_suspended_is_warn():
    finding = check_line_available([_line(5.5, NOW, is_suspended=True)])
    assert finding is not None
    assert finding.reason_code == "LINE_SUSPENDED"


def test_line_available_clean_is_none():
    assert check_line_available([_line(5.5, NOW)]) is None


def test_line_conflict_close_and_different_is_warn():
    lines = [_line(5.5, NOW), _line(6.5, NOW - timedelta(minutes=10))]
    finding = check_line_conflict(lines)
    assert finding is not None
    assert finding.reason_code == "DATA_CONFLICT"


def test_line_conflict_far_apart_is_none():
    lines = [_line(5.5, NOW), _line(6.5, NOW - timedelta(hours=5))]
    assert check_line_conflict(lines) is None


def test_line_conflict_same_value_is_none():
    lines = [_line(5.5, NOW), _line(5.5, NOW - timedelta(minutes=5))]
    assert check_line_conflict(lines) is None


def test_line_conflict_single_line_is_none():
    assert check_line_conflict([_line(5.5, NOW)]) is None


def test_data_stale_old_is_warn():
    finding = check_data_stale(NOW - timedelta(hours=30), NOW, "probable pitcher")
    assert finding is not None
    assert finding.reason_code == "DATA_STALE"


def test_data_stale_fresh_is_none():
    assert check_data_stale(NOW - timedelta(hours=2), NOW, "probable pitcher") is None


def test_data_stale_none_observed_is_none():
    assert check_data_stale(None, NOW, "probable pitcher") is None
