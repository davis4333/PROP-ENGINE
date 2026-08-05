"""historical/backfill.py against a real Postgres session -- idempotency,
resumability, duplicate prevention, actual-starter identification,
normalization, and structural isolation from the live point-in-time
pipeline. Real MLB game-feed/schedule response shapes (respx-mocked),
synthetic game_pks (900000000+, well outside any real MLB gamePk range)
so nothing here can collide with real backfilled data from an actual run.

Uses its own `historical_session` fixture rather than the shared
`db_session` fixture (tests/conftest.py): historical/backfill.py calls
session.commit() itself (a deliberate design choice -- see its module
docstring -- so a multi-year backfill survives a process restart without
losing already-completed work), which is incompatible with db_session's
rollback-after-test isolation (a commit on a connection with an
externally-begun transaction ends that transaction for real). This
fixture instead cleans up explicitly, scoped to this file's own synthetic
IDs only.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Generator
from datetime import date

import httpx
import pytest
import respx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

import cassandra.decision.engine as decision_engine
import cassandra.features.builders as features_builders
import cassandra.models.baseline as models_baseline
import cassandra.pit.asof as pit_asof
import cassandra.pit.snapshot_builder as pit_snapshot_builder
from cassandra.db.models.historical import (
    BackfillItem,
    BackfillRun,
    HistoricalLineup,
    HistoricalPitcherStart,
)
from cassandra.db.models.identity import Game, Team, Venue
from cassandra.historical.backfill import (
    BACKFILL_SOURCE_NAME,
    BackfillConfig,
    _ensure_backfill_source,
    discover_games_for_season,
    process_game_feed,
)

GAME_A = 900000001
GAME_B = 900000002
TEAM_HOME = 900001
TEAM_AWAY = 900002
PITCHER_STARTER_HOME = 900101
PITCHER_RELIEVER_HOME = 900102
PITCHER_STARTER_AWAY = 900201


@pytest.fixture
def historical_session(db_engine) -> Generator[Session, None, None]:
    session_factory = sessionmaker(bind=db_engine, future=True)
    session = session_factory()
    try:
        yield session
    finally:
        session.rollback()
        synthetic_pks = [GAME_A, GAME_B]
        session.execute(
            delete(HistoricalPitcherStart).where(HistoricalPitcherStart.mlb_game_pk.in_(synthetic_pks))
        )
        session.execute(delete(HistoricalLineup).where(HistoricalLineup.mlb_game_pk.in_(synthetic_pks)))
        session.execute(
            delete(BackfillItem).where(BackfillItem.work_key.in_([str(pk) for pk in synthetic_pks]))
        )
        session.execute(
            delete(BackfillItem).where(
                BackfillItem.domain == "schedule", BackfillItem.work_key.like("1899:%")
            )
        )
        session.execute(delete(BackfillRun).where(BackfillRun.requested_start_date == date(1899, 1, 1)))
        session.execute(delete(BackfillRun).where(BackfillRun.domain == "test"))
        session.execute(delete(Game).where(Game.mlb_game_pk.in_(synthetic_pks)))
        session.execute(delete(Team).where(Team.mlb_team_id.in_([TEAM_HOME, TEAM_AWAY])))
        session.execute(delete(Venue).where(Venue.mlb_venue_id == 999999))
        session.commit()
        session.close()


def _feed_payload(
    *,
    game_pk: int,
    status: str = "Final",
    official_date: str = "2023-04-03",
) -> dict:
    return {
        "gameData": {
            "status": {"abstractGameState": status},
            "datetime": {"officialDate": official_date},
        },
        "liveData": {
            "boxscore": {
                "teams": {
                    "home": {
                        "team": {"id": TEAM_HOME},
                        "battingOrder": [700001],
                        "players": {
                            f"ID{PITCHER_STARTER_HOME}": {
                                "person": {"id": PITCHER_STARTER_HOME, "fullName": "Home Starter"},
                                "battingOrder": None,
                                "position": {"abbreviation": "P"},
                                "stats": {
                                    "pitching": {
                                        "gamesStarted": 1,
                                        "battersFaced": 24,
                                        "strikeOuts": 7,
                                        "numberOfPitches": 92,
                                        "strikes": 60,
                                        "balls": 32,
                                        "hits": 5,
                                        "baseOnBalls": 2,
                                        "hitBatsmen": 0,
                                        "homeRuns": 1,
                                        "earnedRuns": 2,
                                        "runs": 2,
                                        "outs": 18,
                                        "inningsPitched": "6.0",
                                        "note": "(W, 3-1)",
                                    }
                                },
                            },
                            f"ID{PITCHER_RELIEVER_HOME}": {
                                "person": {"id": PITCHER_RELIEVER_HOME, "fullName": "Home Reliever"},
                                "battingOrder": None,
                                "position": {"abbreviation": "P"},
                                "stats": {
                                    "pitching": {
                                        "gamesStarted": 0,
                                        "battersFaced": 4,
                                        "strikeOuts": 1,
                                        "numberOfPitches": 15,
                                        "strikes": 10,
                                        "balls": 5,
                                        "hits": 1,
                                        "baseOnBalls": 0,
                                        "hitBatsmen": 0,
                                        "homeRuns": 0,
                                        "earnedRuns": 0,
                                        "runs": 0,
                                        "outs": 3,
                                        "inningsPitched": "1.0",
                                        "note": None,
                                    }
                                },
                            },
                            "ID700001": {
                                "person": {"id": 700001, "fullName": "Home Leadoff"},
                                "battingOrder": "100",
                                "position": {"abbreviation": "CF"},
                                "stats": {},
                            },
                        },
                    },
                    "away": {
                        "team": {"id": TEAM_AWAY},
                        "battingOrder": [800001],
                        "players": {
                            f"ID{PITCHER_STARTER_AWAY}": {
                                "person": {"id": PITCHER_STARTER_AWAY, "fullName": "Away Starter"},
                                "battingOrder": None,
                                "position": {"abbreviation": "P"},
                                "stats": {
                                    "pitching": {
                                        "gamesStarted": 1,
                                        "battersFaced": 22,
                                        "strikeOuts": 5,
                                        "numberOfPitches": 88,
                                        "strikes": 55,
                                        "balls": 33,
                                        "hits": 6,
                                        "baseOnBalls": 3,
                                        "hitBatsmen": 1,
                                        "homeRuns": 0,
                                        "earnedRuns": 3,
                                        "runs": 3,
                                        "outs": 15,
                                        "inningsPitched": "5.0",
                                        "note": "(L, 1-2)",
                                    }
                                },
                            },
                            "ID800001": {
                                "person": {"id": 800001, "fullName": "Away Leadoff"},
                                "battingOrder": "100",
                                "position": {"abbreviation": "2B"},
                                "stats": {},
                            },
                        },
                    },
                }
            }
        },
    }


LIVE_FEED_URL_A = f"https://statsapi.mlb.com/api/v1.1/game/{GAME_A}/feed/live"
LIVE_FEED_URL_B = f"https://statsapi.mlb.com/api/v1.1/game/{GAME_B}/feed/live"


def _config() -> BackfillConfig:
    return BackfillConfig(start_date=date(2023, 4, 3), end_date=date(2023, 4, 3), request_delay_seconds=0.0)


def _run(session: Session) -> BackfillRun:
    """A bare BackfillRun row + registered source, without going through
    run_backfill()'s own schedule-discovery step -- these tests exercise
    process_game_feed() directly against a known synthetic game_pk, and
    don't need (or want to have to mock) a schedule fetch too."""
    run = BackfillRun(
        backfill_run_id=f"test-run-{id(session)}",
        requested_start_date=date(2023, 4, 3),
        requested_end_date=date(2023, 4, 3),
        status="running",
        source=BACKFILL_SOURCE_NAME,
        domain="test",
        config={},
    )
    session.add(run)
    _ensure_backfill_source(session)
    session.commit()
    return run


# --- actual-starter identification / outcome / lineup normalization -----


@respx.mock
def test_process_game_feed_identifies_actual_starters_not_probables(historical_session):
    respx.get(LIVE_FEED_URL_A).mock(return_value=httpx.Response(200, json=_feed_payload(game_pk=GAME_A)))
    run = _run(historical_session)

    outcome = process_game_feed(
        historical_session,
        httpx.Client(),
        game_pk=GAME_A,
        source_id=BACKFILL_SOURCE_NAME,
        config=_config(),
        run=run,
    )
    assert outcome == "succeeded"

    starter = historical_session.execute(
        select(HistoricalPitcherStart).where(
            HistoricalPitcherStart.mlb_game_pk == GAME_A,
            HistoricalPitcherStart.player_mlb_id == PITCHER_STARTER_HOME,
        )
    ).scalar_one()
    reliever = historical_session.execute(
        select(HistoricalPitcherStart).where(
            HistoricalPitcherStart.mlb_game_pk == GAME_A,
            HistoricalPitcherStart.player_mlb_id == PITCHER_RELIEVER_HOME,
        )
    ).scalar_one()

    assert starter.is_starter is True
    assert reliever.is_starter is False
    # Directive non-negotiable #6: an actual historical starter identified
    # from the box score is explicitly NOT the same claim as a live
    # pregame-confirmed probable pitcher.
    assert starter.pregame_starter_confirmation_captured is False
    assert reliever.pregame_starter_confirmation_captured is False


@respx.mock
def test_process_game_feed_normalizes_pitcher_outcome_fields(historical_session):
    respx.get(LIVE_FEED_URL_A).mock(return_value=httpx.Response(200, json=_feed_payload(game_pk=GAME_A)))
    run = _run(historical_session)
    process_game_feed(
        historical_session,
        httpx.Client(),
        game_pk=GAME_A,
        source_id=BACKFILL_SOURCE_NAME,
        config=_config(),
        run=run,
    )

    starter = historical_session.execute(
        select(HistoricalPitcherStart).where(
            HistoricalPitcherStart.mlb_game_pk == GAME_A,
            HistoricalPitcherStart.player_mlb_id == PITCHER_STARTER_HOME,
        )
    ).scalar_one()

    assert starter.batters_faced == 24
    assert starter.strikeouts == 7
    assert starter.pitches_thrown == 92
    assert starter.strikes == 60
    assert starter.balls == 32
    assert starter.hits_allowed == 5
    assert starter.walks == 2
    assert starter.hit_batters == 0
    assert starter.home_runs_allowed == 1
    assert starter.earned_runs == 2
    assert starter.runs_allowed == 2
    assert starter.outs_recorded == 18
    assert float(starter.innings_pitched) == 6.0
    assert starter.decision == "(W, 3-1)"
    assert starter.team_mlb_id == TEAM_HOME
    assert starter.opponent_mlb_id == TEAM_AWAY
    assert starter.game_date == date(2023, 4, 3)
    assert starter.capture_mode == "HISTORICAL_RECONSTRUCTED"


@respx.mock
def test_process_game_feed_normalizes_lineups(historical_session):
    respx.get(LIVE_FEED_URL_A).mock(return_value=httpx.Response(200, json=_feed_payload(game_pk=GAME_A)))
    run = _run(historical_session)
    process_game_feed(
        historical_session,
        httpx.Client(),
        game_pk=GAME_A,
        source_id=BACKFILL_SOURCE_NAME,
        config=_config(),
        run=run,
    )

    home_leadoff = historical_session.execute(
        select(HistoricalLineup).where(
            HistoricalLineup.mlb_game_pk == GAME_A, HistoricalLineup.player_mlb_id == 700001
        )
    ).scalar_one()
    assert home_leadoff.batting_order == "100"
    assert home_leadoff.position == "CF"
    assert home_leadoff.team_mlb_id == TEAM_HOME
    assert home_leadoff.capture_mode == "HISTORICAL_ACTUAL"


# --- idempotency / duplicate prevention / resumability -------------------


@respx.mock
def test_process_game_feed_is_idempotent_and_never_refetches_a_succeeded_game(historical_session):
    route = respx.get(LIVE_FEED_URL_A).mock(
        return_value=httpx.Response(200, json=_feed_payload(game_pk=GAME_A))
    )
    run = _run(historical_session)
    config = _config()

    first = process_game_feed(
        historical_session,
        httpx.Client(),
        game_pk=GAME_A,
        source_id=BACKFILL_SOURCE_NAME,
        config=config,
        run=run,
    )
    second = process_game_feed(
        historical_session,
        httpx.Client(),
        game_pk=GAME_A,
        source_id=BACKFILL_SOURCE_NAME,
        config=config,
        run=run,
    )

    assert first == "succeeded"
    assert second == "succeeded"
    assert route.call_count == 1  # the second call never hit the network at all

    rows = (
        historical_session.execute(
            select(HistoricalPitcherStart).where(HistoricalPitcherStart.mlb_game_pk == GAME_A)
        )
        .scalars()
        .all()
    )
    assert (
        len(rows) == 3
    )  # exactly one row per pitcher (3 pitchers appear in the fixture payload), no duplicates from the rerun


def test_upsert_by_natural_key_prevents_duplicates_and_applies_corrections(historical_session):
    """Duplicate prevention at the lowest level: two writes for the exact
    same (game, player) natural key -- e.g. a genuine correction, or an
    accidental double-run bypassing the BackfillItem check entirely --
    must never produce two rows, and the second write's values must win
    (a correction, not silently ignored)."""
    from datetime import UTC, datetime

    from cassandra.historical.backfill import _upsert_historical_pitcher_start

    _ensure_backfill_source(historical_session)
    historical_session.commit()

    common = {
        "mlb_game_pk": GAME_A,
        "game_date_val": date(2023, 4, 3),
        "player_mlb_id": PITCHER_STARTER_HOME,
        "team_mlb_id": TEAM_HOME,
        "opponent_mlb_id": TEAM_AWAY,
        "is_starter": True,
        "person": {"id": PITCHER_STARTER_HOME, "fullName": "Home Starter"},
        "game_status": "Final",
        "source_id": BACKFILL_SOURCE_NAME,
        "backfill_run_id": None,
    }

    now = datetime.now(UTC)
    _upsert_historical_pitcher_start(
        historical_session, pitching={"strikeOuts": 5, "battersFaced": 20}, observed_at=now, **common
    )
    _upsert_historical_pitcher_start(
        historical_session, pitching={"strikeOuts": 8, "battersFaced": 25}, observed_at=now, **common
    )
    historical_session.flush()

    rows = (
        historical_session.execute(
            select(HistoricalPitcherStart).where(
                HistoricalPitcherStart.mlb_game_pk == GAME_A,
                HistoricalPitcherStart.player_mlb_id == PITCHER_STARTER_HOME,
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].strikeouts == 8  # the later write's values won, not the first


@respx.mock
def test_process_game_feed_one_failing_game_does_not_block_another(historical_session):
    respx.get(LIVE_FEED_URL_A).mock(return_value=httpx.Response(200, json=_feed_payload(game_pk=GAME_A)))
    respx.get(LIVE_FEED_URL_B).mock(return_value=httpx.Response(500))
    run = _run(historical_session)
    config = BackfillConfig(
        start_date=date(2023, 4, 3), end_date=date(2023, 4, 3), request_delay_seconds=0.0, max_retries=1
    )

    outcome_b = process_game_feed(
        historical_session,
        httpx.Client(),
        game_pk=GAME_B,
        source_id=BACKFILL_SOURCE_NAME,
        config=config,
        run=run,
    )
    outcome_a = process_game_feed(
        historical_session,
        httpx.Client(),
        game_pk=GAME_A,
        source_id=BACKFILL_SOURCE_NAME,
        config=config,
        run=run,
    )

    assert outcome_b == "failed"
    assert outcome_a == "succeeded"
    a_rows = (
        historical_session.execute(
            select(HistoricalPitcherStart).where(HistoricalPitcherStart.mlb_game_pk == GAME_A)
        )
        .scalars()
        .all()
    )
    assert len(a_rows) == 3

    failed_item = historical_session.execute(
        select(BackfillItem).where(BackfillItem.domain == "game_feed", BackfillItem.work_key == str(GAME_B))
    ).scalar_one()
    assert failed_item.status == "failed"
    assert failed_item.last_error is not None


@respx.mock
def test_process_game_feed_marks_not_yet_final_as_skipped_not_failed(historical_session):
    respx.get(LIVE_FEED_URL_A).mock(
        return_value=httpx.Response(200, json=_feed_payload(game_pk=GAME_A, status="Live"))
    )
    run = _run(historical_session)
    outcome = process_game_feed(
        historical_session,
        httpx.Client(),
        game_pk=GAME_A,
        source_id=BACKFILL_SOURCE_NAME,
        config=_config(),
        run=run,
    )

    assert outcome == "skipped"
    item = historical_session.execute(
        select(BackfillItem).where(BackfillItem.domain == "game_feed", BackfillItem.work_key == str(GAME_A))
    ).scalar_one()
    assert item.status == "skipped"
    rows = (
        historical_session.execute(
            select(HistoricalPitcherStart).where(HistoricalPitcherStart.mlb_game_pk == GAME_A)
        )
        .scalars()
        .all()
    )
    assert rows == []


# --- schedule discovery: window-keyed idempotency, game-type classification


SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"


def _schedule_game(game_pk: int, game_type: str, iso_date: str) -> dict:
    return {
        "gamePk": game_pk,
        "gameType": game_type,
        "season": "1899",
        "gameDate": f"{iso_date}T17:05:00Z",
        "officialDate": iso_date,
        "status": {"abstractGameState": "Final"},
        "teams": {
            "home": {"team": {"id": TEAM_HOME, "name": "Synthetic Home"}},
            "away": {"team": {"id": TEAM_AWAY, "name": "Synthetic Away"}},
        },
        "venue": {"id": 999999, "name": "Synthetic Park"},
    }


@respx.mock
def test_discover_games_classifies_regular_season_vs_spring_training(historical_session):
    respx.get(SCHEDULE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "dates": [
                    {
                        "games": [
                            _schedule_game(GAME_A, "R", "1899-04-03"),
                            _schedule_game(GAME_B, "S", "1899-03-01"),
                        ]
                    }
                ]
            },
        )
    )
    run = BackfillRun(
        backfill_run_id="test-run-discover",
        requested_start_date=date(1899, 1, 1),
        requested_end_date=date(1899, 12, 31),
        status="running",
        source="test",
        domain="test",
        config={},
    )
    historical_session.add(run)
    historical_session.commit()

    game_pks = discover_games_for_season(
        historical_session,
        httpx.Client(),
        season=1899,
        window_start=date(1899, 1, 1),
        window_end=date(1899, 12, 31),
        config=BackfillConfig(
            start_date=date(1899, 1, 1), end_date=date(1899, 12, 31), request_delay_seconds=0.0
        ),
        run=run,
    )

    assert set(game_pks) == {GAME_A, GAME_B}
    regular = historical_session.get(Game, f"mlb_game_{GAME_A}")
    spring = historical_session.get(Game, f"mlb_game_{GAME_B}")
    assert regular.game_type == "R"
    assert spring.game_type == "S"
    assert regular.season == 1899
    historical_session.commit()
    # cleanup (BackfillItem before BackfillRun, FK order) happens in the fixture teardown


@respx.mock
def test_discover_games_for_a_new_wider_window_is_not_short_circuited_by_an_earlier_narrow_one(
    historical_session,
):
    """Regression test for a real bug found and fixed during this build:
    backfill_items for schedule discovery were originally keyed by season
    alone, so a narrow-window discovery (e.g. a single day) would
    permanently mark the whole season "succeeded," silently short-
    circuiting any later, wider request for the same season without ever
    fetching it. Fixed by keying on (season, window_start, window_end)."""
    narrow_route = respx.get(SCHEDULE_URL, params={"startDate": "1899-04-03", "endDate": "1899-04-03"}).mock(
        return_value=httpx.Response(
            200, json={"dates": [{"games": [_schedule_game(GAME_A, "R", "1899-04-03")]}]}
        )
    )
    wide_route = respx.get(SCHEDULE_URL, params={"startDate": "1899-01-01", "endDate": "1899-12-31"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "dates": [
                    {
                        "games": [
                            _schedule_game(GAME_A, "R", "1899-04-03"),
                            _schedule_game(GAME_B, "R", "1899-05-01"),
                        ]
                    }
                ]
            },
        )
    )
    run = BackfillRun(
        backfill_run_id="test-run-window",
        requested_start_date=date(1899, 1, 1),
        requested_end_date=date(1899, 12, 31),
        status="running",
        source="test",
        domain="test",
        config={},
    )
    historical_session.add(run)
    historical_session.commit()

    narrow_config = BackfillConfig(
        start_date=date(1899, 4, 3), end_date=date(1899, 4, 3), request_delay_seconds=0.0
    )
    narrow_pks = discover_games_for_season(
        historical_session,
        httpx.Client(),
        season=1899,
        window_start=date(1899, 4, 3),
        window_end=date(1899, 4, 3),
        config=narrow_config,
        run=run,
    )
    assert narrow_pks == [GAME_A]
    assert narrow_route.called

    wide_config = BackfillConfig(
        start_date=date(1899, 1, 1), end_date=date(1899, 12, 31), request_delay_seconds=0.0
    )
    wide_pks = discover_games_for_season(
        historical_session,
        httpx.Client(),
        season=1899,
        window_start=date(1899, 1, 1),
        window_end=date(1899, 12, 31),
        config=wide_config,
        run=run,
    )
    assert wide_route.called, "the wider window must trigger a real fetch, not be short-circuited"
    assert set(wide_pks) == {GAME_A, GAME_B}
    historical_session.commit()
    # cleanup (BackfillItem before BackfillRun, FK order) happens in the fixture teardown


# --- structural isolation from the live point-in-time pipeline -----------


def _referenced_names(module) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }


@pytest.mark.parametrize(
    "module",
    [pit_asof, pit_snapshot_builder, features_builders, models_baseline, decision_engine],
    ids=["pit.asof", "pit.snapshot_builder", "features.builders", "models.baseline", "decision.engine"],
)
def test_live_pit_pipeline_never_references_historical_reconstruction_tables(module):
    """The directive's non-negotiable #2: historical backfill must never
    weaken the live as-of pipeline. The strongest version of that
    guarantee here is structural, not just a design intent -- these
    modules must not even reference HistoricalPitcherStart/
    HistoricalLineup at all, so there is no code path by which a
    backfilled row (whose ingested_at is real backfill-time, not the
    historical date it describes) could reach a live decision."""
    referenced = _referenced_names(module)
    assert "HistoricalPitcherStart" not in referenced
    assert "HistoricalLineup" not in referenced
    assert "historical_pitcher_starts" not in referenced
    assert "historical_lineups" not in referenced


def test_historical_backfill_module_never_imports_the_live_asof_gate():
    """The flip side: historical/backfill.py has its own separate
    resumability/idempotency mechanism (BackfillItem) and must not lean
    on pit/asof.py's ingested_at-based cutoff gate at all -- that gate
    means something specific (leakage safety for the live pipeline) that
    doesn't apply to a bulk historical write."""
    import cassandra.historical.backfill as historical_backfill

    referenced = _referenced_names(historical_backfill)
    assert "latest_as_of" not in referenced
    assert "all_as_of" not in referenced
    assert "latest_grouped_as_of" not in referenced
