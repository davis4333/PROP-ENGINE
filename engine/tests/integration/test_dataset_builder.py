"""historical/dataset_builder.py + historical/availability.py against a
real Postgres session -- specifically that a training-dataset row can
never see its own target game's outcome or any later game (the core
leakage guarantee this module exists to provide), and that the manifest
honestly records what tier/feature groups a build actually covers.

Synthetic game_pks (900010000+, well outside any real MLB gamePk range)
and its own cleanup fixture, for the same reason
test_historical_backfill.py uses one: this code (transitively, via
BackfillItem/HistoricalPitcherStart writes elsewhere) is exercised
against a session that may commit, so the shared rollback-based
`db_session` fixture's isolation doesn't apply here either -- though this
suite itself only ever reads/writes via ORM `session.flush()`/explicit
cleanup, never `session.commit()`, so a plain rollback would also work;
the explicit cleanup is kept for consistency with the sibling suite and
so leftover rows never survive a failed assertion mid-test.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Generator
from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from cassandra.db.models.historical import HistoricalPitcherStart, HistoricalWeatherObservation
from cassandra.db.models.identity import Game, Venue
from cassandra.db.models.sources import Source
from cassandra.historical.availability import eligible_prior_starts
from cassandra.historical.dataset_builder import (
    DATASET_TIER_STRICT_LIVE_COMPATIBLE,
    build_training_dataset,
)

PITCHER_ID = 900010101
GAME_PKS = [900010001, 900010002, 900010003, 900010004]
WEATHER_GAME_PKS = [900010010, 900010011, 900010012, 900010013, 900010014]
VENUE_MLB_ID = 900099
VENUE_ID = "test-dataset-builder-venue"
SOURCE_ID = "test_dataset_builder_source"


@pytest.fixture
def dataset_session(db_engine, tmp_path) -> Generator[Session, None, None]:
    session_factory = sessionmaker(bind=db_engine, future=True)
    session = session_factory()
    try:
        yield session
    finally:
        session.rollback()
        all_pks = GAME_PKS + WEATHER_GAME_PKS
        session.execute(delete(HistoricalPitcherStart).where(HistoricalPitcherStart.mlb_game_pk.in_(all_pks)))
        session.execute(
            delete(HistoricalWeatherObservation).where(HistoricalWeatherObservation.mlb_game_pk.in_(all_pks))
        )
        session.execute(delete(Game).where(Game.mlb_game_pk.in_(all_pks)))
        session.execute(delete(Venue).where(Venue.venue_id == VENUE_ID))
        session.commit()
        session.close()


def _seed_source(session: Session) -> None:
    stmt = pg_insert(Source).values(source_id=SOURCE_ID, name=SOURCE_ID, kind="pitcher_stats")
    stmt = stmt.on_conflict_do_nothing(index_elements=[Source.source_id])
    session.execute(stmt)


def _seed_venue(session: Session) -> None:
    stmt = pg_insert(Venue).values(venue_id=VENUE_ID, mlb_venue_id=VENUE_MLB_ID, name="Test Dataset Park")
    stmt = stmt.on_conflict_do_nothing(index_elements=[Venue.venue_id])
    session.execute(stmt)


def _seed_game(
    session: Session,
    *,
    mlb_game_pk: int,
    game_date: date,
    season: int,
    game_type: str = "R",
    venue_id: str | None = None,
) -> None:
    session.add(
        Game(
            game_id=f"test-game-{mlb_game_pk}",
            mlb_game_pk=mlb_game_pk,
            game_date=datetime.combine(game_date, time.min),
            scheduled_start_utc=datetime.combine(game_date, time.min, tzinfo=UTC),
            status="Final",
            game_type=game_type,
            season=season,
            venue_id=venue_id,
        )
    )


def _seed_weather(session: Session, *, mlb_game_pk: int, game_date: date, temp_f: float) -> None:
    session.add(
        HistoricalWeatherObservation(
            mlb_game_pk=mlb_game_pk,
            game_date=game_date,
            venue_mlb_id=VENUE_MLB_ID,
            condition="Clear",
            temp_f=temp_f,
            wind_mph=5.0,
            wind_detail="Out To CF",
            source_id=SOURCE_ID,
            observed_at=datetime.combine(game_date, time.min, tzinfo=UTC),
            payload={"condition": "Clear", "temp": str(temp_f), "wind": "5 mph, Out To CF"},
        )
    )


def _seed_start(
    session: Session,
    *,
    mlb_game_pk: int,
    game_date: date,
    batters_faced: int,
    strikeouts: int,
    is_starter: bool = True,
    game_status: str = "Final",
) -> None:
    session.add(
        HistoricalPitcherStart(
            mlb_game_pk=mlb_game_pk,
            game_date=game_date,
            player_mlb_id=PITCHER_ID,
            team_mlb_id=900020001,
            opponent_mlb_id=900020002,
            is_starter=is_starter,
            batters_faced=batters_faced,
            strikeouts=strikeouts,
            pitches_thrown=90,
            innings_pitched=6.0,
            game_status=game_status,
            source_id=SOURCE_ID,
            observed_at=datetime.combine(game_date, time.min, tzinfo=UTC),
            payload={},
        )
    )


def test_eligible_prior_starts_excludes_target_game_and_future_games(dataset_session):
    _seed_source(dataset_session)
    _seed_start(
        dataset_session, mlb_game_pk=GAME_PKS[0], game_date=date(2023, 4, 1), batters_faced=20, strikeouts=6
    )
    _seed_start(
        dataset_session, mlb_game_pk=GAME_PKS[1], game_date=date(2023, 4, 8), batters_faced=22, strikeouts=8
    )
    _seed_start(
        dataset_session, mlb_game_pk=GAME_PKS[2], game_date=date(2023, 4, 15), batters_faced=25, strikeouts=10
    )
    dataset_session.flush()

    prior = eligible_prior_starts(dataset_session, player_mlb_id=PITCHER_ID, before_date=date(2023, 4, 8))

    # Only the 4/1 start is strictly before the 4/8 target -- the 4/8
    # start itself and the later 4/15 start must never appear, even
    # though both are on record for this pitcher.
    assert [s.mlb_game_pk for s in prior] == [GAME_PKS[0]]


def test_eligible_prior_starts_excludes_non_final_games(dataset_session):
    _seed_source(dataset_session)
    _seed_start(
        dataset_session,
        mlb_game_pk=GAME_PKS[0],
        game_date=date(2023, 4, 1),
        batters_faced=20,
        strikeouts=6,
        game_status="In Progress",
    )
    dataset_session.flush()

    prior = eligible_prior_starts(dataset_session, player_mlb_id=PITCHER_ID, before_date=date(2023, 4, 8))

    assert prior == []


def test_build_training_dataset_row_features_only_use_earlier_starts(dataset_session, tmp_path):
    _seed_source(dataset_session)
    _seed_game(dataset_session, mlb_game_pk=GAME_PKS[0], game_date=date(1899, 4, 1), season=1899)
    _seed_game(dataset_session, mlb_game_pk=GAME_PKS[1], game_date=date(1899, 4, 8), season=1899)
    _seed_game(dataset_session, mlb_game_pk=GAME_PKS[2], game_date=date(1899, 4, 15), season=1899)
    # An earlier start with a very high K rate (so it's easy to detect if
    # a later row's features were accidentally computed from it).
    _seed_start(
        dataset_session, mlb_game_pk=GAME_PKS[0], game_date=date(1899, 4, 1), batters_faced=20, strikeouts=6
    )
    # The target row: its own strikeouts (12) must appear only as the
    # label, never folded into its own recent_k_rate feature.
    _seed_start(
        dataset_session, mlb_game_pk=GAME_PKS[1], game_date=date(1899, 4, 8), batters_faced=20, strikeouts=12
    )
    # A later start with a wildly different outcome -- must not affect
    # the 4/8 row's features either, since it hasn't happened yet as of
    # 4/8.
    _seed_start(
        dataset_session, mlb_game_pk=GAME_PKS[2], game_date=date(1899, 4, 15), batters_faced=20, strikeouts=1
    )
    dataset_session.flush()

    manifest = build_training_dataset(dataset_session, seasons=[1899], output_dir=tmp_path, game_types=("R",))

    assert manifest.row_count == 3
    assert manifest.tier == DATASET_TIER_STRICT_LIVE_COMPATIBLE

    rows = _read_rows(manifest.output_path)
    by_game = {r["mlb_game_pk"]: r for r in rows}

    first = by_game[GAME_PKS[0]]
    assert first["prior_starts_available"] == 0
    assert first["expected_bf_tier"] == "league_default"
    assert first["actual_strikeouts"] == 6

    second = by_game[GAME_PKS[1]]
    assert second["prior_starts_available"] == 1
    # season_average tier since only 1 prior start exists (< MIN_STARTS_FOR_RECENT)
    assert second["expected_bf_tier"] == "season_average"
    assert second["expected_bf"] == 20.0
    assert second["actual_strikeouts"] == 12  # label only, not a feature input

    third = by_game[GAME_PKS[2]]
    assert third["prior_starts_available"] == 2
    assert third["actual_strikeouts"] == 1
    # Confirms the 4/15 row's features were derived from the two earlier
    # starts (20, 20 BF) and NOT contaminated by its own 20 BF outcome in
    # a way that would be indistinguishable from this assertion alone --
    # the real guarantee is structural (eligible_prior_starts' `<
    # before_date` filter), verified directly above.
    assert third["expected_bf"] == 20.0


def test_build_training_dataset_excludes_non_final_and_non_starter_appearances(dataset_session, tmp_path):
    _seed_source(dataset_session)
    _seed_game(dataset_session, mlb_game_pk=GAME_PKS[0], game_date=date(1899, 4, 1), season=1899)
    _seed_game(dataset_session, mlb_game_pk=GAME_PKS[1], game_date=date(1899, 4, 8), season=1899)
    _seed_start(
        dataset_session,
        mlb_game_pk=GAME_PKS[0],
        game_date=date(1899, 4, 1),
        batters_faced=20,
        strikeouts=6,
        is_starter=False,
    )
    _seed_start(
        dataset_session,
        mlb_game_pk=GAME_PKS[1],
        game_date=date(1899, 4, 8),
        batters_faced=20,
        strikeouts=6,
        game_status="Postponed",
    )
    dataset_session.flush()

    manifest = build_training_dataset(dataset_session, seasons=[1899], output_dir=tmp_path)

    assert manifest.row_count == 0


def test_build_training_dataset_respects_game_type_filter(dataset_session, tmp_path):
    _seed_source(dataset_session)
    _seed_game(
        dataset_session, mlb_game_pk=GAME_PKS[0], game_date=date(1899, 3, 1), season=1899, game_type="S"
    )
    _seed_start(
        dataset_session, mlb_game_pk=GAME_PKS[0], game_date=date(1899, 3, 1), batters_faced=20, strikeouts=6
    )
    dataset_session.flush()

    default_manifest = build_training_dataset(dataset_session, seasons=[1899], output_dir=tmp_path)
    assert default_manifest.row_count == 0  # game_types=("R",) default excludes spring training

    spring_manifest = build_training_dataset(
        dataset_session, seasons=[1899], output_dir=tmp_path, game_types=("S",)
    )
    assert spring_manifest.row_count == 1


def test_manifest_honestly_lists_excluded_feature_groups(dataset_session, tmp_path):
    manifest = build_training_dataset(dataset_session, seasons=[1899], output_dir=tmp_path)
    for group in ("pitch_mix", "opponent_rolling_k_context"):
        assert group in manifest.excluded_feature_groups
    # park_factor/weather are now real (park_factors.py,
    # HistoricalWeatherObservation) -- no longer blanket-excluded.
    for group in ("park_factor", "weather"):
        assert group not in manifest.excluded_feature_groups
    assert manifest.row_count == 0


def _read_rows(output_path: str) -> list[dict]:
    with gzip.open(output_path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


# --- weather / park factor wiring (Phase 4) -------------------------------


def test_weather_available_flips_true_only_when_a_row_actually_has_a_weather_observation(
    dataset_session, tmp_path
):
    # season=1899 (not a real backfilled season, matching
    # test_historical_backfill.py's convention) -- 2023-2025 real backfill
    # data lives in this same shared dev database, and a season shared
    # with it would silently pull thousands of real rows into this test's
    # assertions alongside the synthetic ones (found by an independent
    # audit of this exact test using season=2023 originally).
    _seed_source(dataset_session)
    _seed_venue(dataset_session)
    _seed_game(dataset_session, mlb_game_pk=GAME_PKS[0], game_date=date(1899, 4, 1), season=1899)
    _seed_game(
        dataset_session, mlb_game_pk=GAME_PKS[1], game_date=date(1899, 4, 8), season=1899, venue_id=VENUE_ID
    )
    _seed_start(
        dataset_session, mlb_game_pk=GAME_PKS[0], game_date=date(1899, 4, 1), batters_faced=20, strikeouts=6
    )
    _seed_start(
        dataset_session, mlb_game_pk=GAME_PKS[1], game_date=date(1899, 4, 8), batters_faced=20, strikeouts=6
    )
    _seed_weather(dataset_session, mlb_game_pk=GAME_PKS[1], game_date=date(1899, 4, 8), temp_f=45.0)
    dataset_session.flush()

    manifest = build_training_dataset(dataset_session, seasons=[1899], output_dir=tmp_path)
    rows = _read_rows(manifest.output_path)
    by_game = {r["mlb_game_pk"]: r for r in rows}

    # No weather row seeded for GAME_PKS[0] -- honestly unavailable, not a
    # silently-assumed neutral value.
    assert by_game[GAME_PKS[0]]["weather_available"] is False
    assert by_game[GAME_PKS[0]]["weather_adjustment"] == 1.0  # NEUTRAL_WEATHER_ADJUSTMENT
    assert by_game[GAME_PKS[0]]["weather_source"] is None

    # GAME_PKS[1] has a real 45F observation -- compute_weather_adjustment's
    # cold-weather boost (see features/builders.py) should apply, and the
    # row must flag this as ACTUAL (not forecast) weather -- see
    # WEATHER_SOURCE_ACTUAL's docstring.
    assert by_game[GAME_PKS[1]]["weather_available"] is True
    assert by_game[GAME_PKS[1]]["weather_adjustment"] == 1.02
    assert by_game[GAME_PKS[1]]["weather_source"] == "actual"


def test_park_factor_available_flips_true_once_the_venue_clears_the_sample_threshold_and_never_leaks(
    dataset_session, tmp_path
):
    """MIN_BATTERS_FACED_FOR_PARK_FACTOR=400 (park_factors.py). Games 1-4
    below (100 BF each) accumulate exactly 400 BF of STRICTLY PRIOR
    history at the venue by the time game 5 is evaluated -- game 5 should
    be the first row to see park_factor_available=True, and its own (very
    high, 50%) K rate must not have influenced the factor it was assigned,
    since that factor was computed from games 1-4 only."""
    # season=1899, same reasoning as the weather test above -- this
    # test's league-baseline assertions (e.g. park_k_factor == 1.0)
    # specifically depend on VENUE_A/VENUE_B being the ONLY data in the
    # accumulator; a season colliding with real backfilled data would
    # silently invalidate them.
    _seed_source(dataset_session)
    _seed_venue(dataset_session)
    for i, game_pk in enumerate(WEATHER_GAME_PKS):
        game_date = date(1899, 4, 1 + i)
        _seed_game(dataset_session, mlb_game_pk=game_pk, game_date=game_date, season=1899, venue_id=VENUE_ID)
        # Games 1-4: a modest, consistent 20% K rate. Game 5 (the target
        # row under test): a wildly different 50% rate that must not leak
        # into its own park factor.
        strikeouts = 50 if i == 4 else 20
        _seed_start(
            dataset_session,
            mlb_game_pk=game_pk,
            game_date=game_date,
            batters_faced=100,
            strikeouts=strikeouts,
        )
    dataset_session.flush()

    manifest = build_training_dataset(dataset_session, seasons=[1899], output_dir=tmp_path)
    rows = _read_rows(manifest.output_path)
    by_game = {r["mlb_game_pk"]: r for r in rows}

    assert manifest.coverage_notes["park_factor_available_count"] >= 1

    first_four = [by_game[pk] for pk in WEATHER_GAME_PKS[:4]]
    for row in first_four:
        assert row["park_factor_available"] is False  # below the 400-BF threshold so far

    last_row = by_game[WEATHER_GAME_PKS[4]]
    assert last_row["park_factor_available"] is True
    # Prior games ran at a 20% K rate matching the league (the only venue
    # seeded, so venue rate == league rate at that point) -- neutral, 1.0.
    # If this row's own 50% outcome had leaked into its own factor, this
    # would be pulled well above 1.0.
    assert last_row["park_k_factor"] == 1.0
