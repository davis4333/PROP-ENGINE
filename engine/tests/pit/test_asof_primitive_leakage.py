"""Adversarial point-in-time leakage tests for the as-of primitives
themselves (ADR 0001, CLAUDE.md non-negotiable #2: future-data leakage is
a release blocker). These insert raw rows directly with exact,
hand-controlled `observed_at`/`ingested_at` timestamps -- deliberately
bypassing adapters/ingest_service -- so each test can assert the leakage
boundary down to the exact instant, instead of relying on real-world
timing from an HTTP-mocked ingest.

Every test here tries to make the *wrong* answer look attractive (a
"helpful" late correction, a source that backdates its claimed
observed_at, a row that's the true latest but arrived late) and asserts
the as-of primitives refuse it anyway.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from cassandra.db.models.raw import (
    RawLine,
    RawLineup,
    RawParkFactor,
    RawPitcherGameLog,
    RawProbablePitcher,
    RawWeatherObservation,
)
from cassandra.db.models.sources import Source
from cassandra.pit.asof import all_as_of, latest_as_of, latest_grouped_as_of

CUTOFF = datetime(2024, 4, 1, 18, 0, tzinfo=UTC)
BEFORE = CUTOFF - timedelta(hours=1)
AFTER = CUTOFF + timedelta(hours=1)


def _make_source(session, source_id: str) -> None:
    stmt = pg_insert(Source).values(source_id=source_id, name=source_id, kind="lines")
    stmt = stmt.on_conflict_do_nothing(index_elements=[Source.source_id])
    session.execute(stmt)
    session.flush()


def _make_line(
    session, *, source_id: str, observed_at: datetime, ingested_at: datetime, line: float
) -> RawLine:
    row = RawLine(
        raw_id=uuid.uuid4(),
        source_id=source_id,
        mlb_game_pk=999001,
        player_mlb_id=888001,
        market="pitcher_strikeouts",
        line=line,
        observed_at=observed_at,
        ingested_at=ingested_at,
        payload={"line": line},
    )
    session.add(row)
    session.flush()
    return row


def test_late_arriving_record_excluded_even_though_it_is_the_true_latest(db_session):
    """The core leakage guarantee: a row physically written *after*
    cutoff must never be visible, no matter how much more "correct" or
    "recent" it claims to be."""
    _make_source(db_session, "src-leak-1")
    _make_line(db_session, source_id="src-leak-1", observed_at=BEFORE, ingested_at=BEFORE, line=5.5)
    # A correction arrives later -- physically written after cutoff, even
    # though it *claims* (observed_at) to describe a moment before cutoff.
    _make_line(db_session, source_id="src-leak-1", observed_at=BEFORE, ingested_at=AFTER, line=7.5)

    result = latest_as_of(db_session, RawLine, {"mlb_game_pk": 999001, "player_mlb_id": 888001}, CUTOFF)

    assert result is not None
    assert result.line == 5.5, "the post-cutoff-ingested correction must never leak through"


def test_observed_at_backdating_does_not_bypass_the_ingested_at_gate(db_session):
    """A source could claim ANY observed_at it wants -- ingested_at (real
    wall-clock write time) is the true, unspoofable gate."""
    _make_source(db_session, "src-leak-2")
    # Same instant physically written after cutoff, but observed_at is
    # backdated to look like it happened well before.
    _make_line(
        db_session,
        source_id="src-leak-2",
        observed_at=BEFORE - timedelta(days=30),
        ingested_at=AFTER,
        line=9.5,
    )

    result = latest_as_of(db_session, RawLine, {"mlb_game_pk": 999001, "player_mlb_id": 888001}, CUTOFF)

    assert result is None, "ingested_at after cutoff must exclude the row regardless of observed_at"


def test_observed_at_in_the_future_is_excluded_even_when_ingested_before_cutoff(db_session):
    """The reverse direction: a row ingested before cutoff but claiming to
    describe a moment *after* cutoff must also be excluded -- both
    conditions are independently enforced (AND, not OR)."""
    _make_source(db_session, "src-leak-3")
    _make_line(
        db_session,
        source_id="src-leak-3",
        observed_at=AFTER,
        ingested_at=BEFORE,
        line=11.5,
    )

    result = latest_as_of(db_session, RawLine, {"mlb_game_pk": 999001, "player_mlb_id": 888001}, CUTOFF)

    assert result is None


def test_latest_as_of_picks_the_most_recent_visible_version_not_the_global_latest(db_session):
    """Three versions of the same fact: an old one, a mid one, and a
    post-cutoff "latest" one that must be invisible. The result must be
    the mid one -- proving this isn't just "any row passes," it's
    specifically the most-recent-as-of-cutoff row."""
    _make_source(db_session, "src-leak-4")
    _make_line(
        db_session,
        source_id="src-leak-4",
        observed_at=BEFORE - timedelta(hours=2),
        ingested_at=BEFORE - timedelta(hours=2),
        line=4.5,
    )
    mid = _make_line(db_session, source_id="src-leak-4", observed_at=BEFORE, ingested_at=BEFORE, line=5.5)
    _make_line(db_session, source_id="src-leak-4", observed_at=AFTER, ingested_at=AFTER, line=6.5)

    result = latest_as_of(db_session, RawLine, {"mlb_game_pk": 999001, "player_mlb_id": 888001}, CUTOFF)

    assert result is not None
    assert result.raw_id == mid.raw_id
    assert result.line == 5.5


@pytest.mark.parametrize(
    ("model", "natural_key", "field", "before_value", "after_value"),
    [
        (RawPitcherGameLog, {"player_mlb_id": 888002}, "strikeouts", 5, 99),
        (RawParkFactor, {"venue_id": "mlb_venue_2", "season": 2024}, "k_factor", 1.0, 5.0),
        (RawWeatherObservation, {"venue_id": "mlb_venue_2"}, "temp_f", 70.0, 999.0),
        (
            RawLineup,
            {"mlb_game_pk": 999003, "team_mlb_id": 110},
            "batting_order",
            {"order": [1001], "slots": {"100": 1001}},
            {"order": [9999], "slots": {"100": 9999}},
        ),
    ],
)
def test_all_as_of_never_returns_a_post_cutoff_row_across_raw_tables(
    db_session, model, natural_key, field, before_value, after_value
):
    """Every raw table snapshot_builder actually reads through as_of must
    honor the same leakage boundary -- not just raw_lines."""
    _make_source(db_session, f"src-leak-{model.__tablename__}")
    common = {
        "source_id": f"src-leak-{model.__tablename__}",
        "observed_at": BEFORE,
        "ingested_at": BEFORE,
        "payload": {field: before_value},
        **natural_key,
    }
    if model is RawPitcherGameLog:
        common["stat_date"] = BEFORE
    if model is RawWeatherObservation:
        common["forecast_for"] = BEFORE
    row_before = model(raw_id=uuid.uuid4(), **{**common, field: before_value})
    db_session.add(row_before)

    common_after = dict(common)
    common_after["ingested_at"] = AFTER
    common_after["observed_at"] = AFTER
    row_after = model(raw_id=uuid.uuid4(), **{**common_after, field: after_value})
    db_session.add(row_after)
    db_session.flush()

    results = all_as_of(db_session, model, natural_key, CUTOFF)

    assert len(results) == 1
    assert getattr(results[0], field) == before_value


def test_latest_grouped_as_of_never_leaks_a_post_cutoff_row_per_group(db_session):
    """The home/away-probable-pitcher grouped query used by
    snapshot_builder must apply the same leakage boundary independently
    per group (team_mlb_id), not just overall."""
    _make_source(db_session, "src-leak-grouped")
    game_pk = 999002
    # Home team's real, visible probable pitcher.
    home_row = RawProbablePitcher(
        raw_id=uuid.uuid4(),
        source_id="src-leak-grouped",
        mlb_game_pk=game_pk,
        player_mlb_id=1001,
        team_mlb_id=110,
        is_confirmed=True,
        observed_at=BEFORE,
        ingested_at=BEFORE,
        payload={},
    )
    # Away team's probable pitcher, ingested before cutoff (visible).
    away_visible = RawProbablePitcher(
        raw_id=uuid.uuid4(),
        source_id="src-leak-grouped",
        mlb_game_pk=game_pk,
        player_mlb_id=2001,
        team_mlb_id=141,
        is_confirmed=True,
        observed_at=BEFORE,
        ingested_at=BEFORE,
        payload={},
    )
    # Away team's starter gets scratched/replaced -- the replacement is
    # ingested after cutoff and must not leak in, even though it's the
    # "real" answer as of right now.
    away_replacement = RawProbablePitcher(
        raw_id=uuid.uuid4(),
        source_id="src-leak-grouped",
        mlb_game_pk=game_pk,
        player_mlb_id=2002,
        team_mlb_id=141,
        is_confirmed=True,
        observed_at=AFTER,
        ingested_at=AFTER,
        payload={},
    )
    db_session.add_all([home_row, away_visible, away_replacement])
    db_session.flush()

    results = latest_grouped_as_of(
        db_session, RawProbablePitcher, {"mlb_game_pk": game_pk}, CUTOFF, group_by="team_mlb_id"
    )

    by_team = {r.team_mlb_id: r for r in results}
    assert by_team[141].player_mlb_id == 2001, "the post-cutoff replacement must not leak into the away slot"
    assert by_team[110].player_mlb_id == 1001


@pytest.mark.parametrize("fn", [latest_as_of, all_as_of])
def test_naive_cutoff_datetime_is_rejected(db_session, fn):
    with pytest.raises(ValueError, match="timezone-aware"):
        fn(db_session, RawLine, {"mlb_game_pk": 1}, datetime(2024, 1, 1))


def test_latest_grouped_as_of_rejects_naive_cutoff(db_session):
    with pytest.raises(ValueError, match="timezone-aware"):
        latest_grouped_as_of(
            db_session, RawProbablePitcher, {"mlb_game_pk": 1}, datetime(2024, 1, 1), group_by="team_mlb_id"
        )
