"""grading/scoreboard.py against a real Postgres session -- the
today/7d/30d/all-time track record. Grade rows are inserted directly
(not via grade_projection()) for exact control over `result`, since these
tests are about scoreboard.py's own windowing/aggregation, not the
grading pipeline itself (already covered by test_grading_service.py)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert as pg_insert

from cassandra.db.models.grading import Grade
from cassandra.db.models.identity import Game, Player
from cassandra.db.models.snapshot import Snapshot
from cassandra.decision.engine import decide
from cassandra.grading.scoreboard import build_scoreboard
from cassandra.ledger.service import publish_projection
from cassandra.models.baseline import PoissonStrikeoutDistribution

NOW = datetime.now(UTC)


def _make_snapshot(session) -> Snapshot:
    snap = Snapshot(slate_date=NOW.date(), cutoff_at=NOW, status="frozen")
    session.add(snap)
    session.flush()
    return snap


def _make_game(session, *, game_id: str, scheduled_start_utc: datetime) -> Game:
    stmt = pg_insert(Game).values(
        game_id=game_id,
        mlb_game_pk=int(uuid.uuid4().int % 1_000_000),
        game_date=scheduled_start_utc,
        scheduled_start_utc=scheduled_start_utc,
        home_team_id=None,
        away_team_id=None,
        venue_id=None,
        status="Final",
    )
    session.execute(stmt)
    session.flush()
    return session.get(Game, game_id)


def _make_player(session, *, player_id: str) -> Player:
    stmt = pg_insert(Player).values(
        player_id=player_id, mlb_person_id=int(uuid.uuid4().int % 1_000_000), full_name=f"Test {player_id}"
    )
    session.execute(stmt)
    session.flush()
    return session.get(Player, player_id)


def _publish(
    session,
    *,
    game_id: str,
    player_id: str,
    scheduled_start_utc: datetime,
    line: float | None = 5.5,
    mean: float = 8.0,
    record_label: str = "LIVE",
):
    snapshot = _make_snapshot(session)
    game = _make_game(session, game_id=game_id, scheduled_start_utc=scheduled_start_utc)
    player = _make_player(session, player_id=player_id)
    decision = decide(line, PoissonStrikeoutDistribution(mean=mean), [])
    row = publish_projection(
        session,
        run_id="run-scoreboard",
        snapshot=snapshot,
        game=game,
        player_id=player.player_id,
        line=line,
        feature_set_version="k-features-0.1.0",
        features={},
        model_version="k-model-0.1.0",
        decision=decision,
        as_of=scheduled_start_utc,
        record_label=record_label,
    )
    session.flush()
    return row


def _grade(session, *, projection_id: str, result: str, actual_strikeouts: int | None = None) -> Grade:
    row = Grade(
        grade_id=uuid.uuid4(),
        projection_id=projection_id,
        graded_at=NOW,
        result=result,
        actual_strikeouts=actual_strikeouts,
    )
    session.add(row)
    session.flush()
    return row


def test_empty_scoreboard_has_zero_everything_in_every_window(db_session):
    board = build_scoreboard(db_session)
    for window in (board.today, board.last_7_days, board.last_30_days, board.all_time):
        assert window.wins == 0
        assert window.losses == 0
        assert window.pushes == 0
        assert window.voids == 0
        assert window.no_plays == 0
        assert window.waiting == 0
        assert window.win_rate is None
        assert window.mean_absolute_error is None


def test_todays_win_counts_in_every_window(db_session):
    p = _publish(db_session, game_id="sb-today-game", player_id="sb-today-player", scheduled_start_utc=NOW)
    _grade(db_session, projection_id=p.projection_id, result="WIN", actual_strikeouts=9)

    board = build_scoreboard(db_session)

    assert board.today.wins == 1
    assert board.last_7_days.wins == 1
    assert board.last_30_days.wins == 1
    assert board.all_time.wins == 1
    assert board.today.win_rate == 1.0


def test_a_ten_day_old_loss_is_outside_7d_but_inside_30d_and_all_time(db_session):
    old = NOW - timedelta(days=10)
    p = _publish(db_session, game_id="sb-10d-game", player_id="sb-10d-player", scheduled_start_utc=old)
    _grade(db_session, projection_id=p.projection_id, result="LOSS")

    board = build_scoreboard(db_session)

    assert board.today.losses == 0
    assert board.last_7_days.losses == 0
    assert board.last_30_days.losses == 1
    assert board.all_time.losses == 1


def test_a_forty_day_old_push_only_counts_in_all_time(db_session):
    ancient = NOW - timedelta(days=40)
    p = _publish(db_session, game_id="sb-40d-game", player_id="sb-40d-player", scheduled_start_utc=ancient)
    _grade(db_session, projection_id=p.projection_id, result="PUSH")

    board = build_scoreboard(db_session)

    assert board.last_30_days.pushes == 0
    assert board.all_time.pushes == 1


def test_a_real_over_under_call_with_no_grade_yet_counts_as_waiting_not_a_result(db_session):
    _publish(db_session, game_id="sb-waiting-game", player_id="sb-waiting-player", scheduled_start_utc=NOW)

    board = build_scoreboard(db_session)

    assert board.today.waiting == 1
    assert board.today.wins == 0
    assert board.today.losses == 0


def test_an_ungraded_no_play_is_never_counted_as_waiting(db_session):
    # decision/engine.py forces NO_PLAY/REJECTED when there's no line --
    # nothing was ever recommended, so there's nothing to "wait" on.
    _publish(
        db_session,
        game_id="sb-noplay-waiting-game",
        player_id="sb-noplay-waiting-player",
        scheduled_start_utc=NOW,
        line=None,
    )

    board = build_scoreboard(db_session)

    assert board.today.waiting == 0


def test_a_graded_no_play_counts_as_no_play_not_waiting(db_session):
    p = _publish(
        db_session,
        game_id="sb-noplay-graded-game",
        player_id="sb-noplay-graded-player",
        scheduled_start_utc=NOW,
        line=None,
    )
    _grade(db_session, projection_id=p.projection_id, result="NO_PLAY")

    board = build_scoreboard(db_session)

    assert board.today.no_plays == 1
    assert board.today.waiting == 0


def test_projection_error_is_computed_from_actual_vs_projected_mean(db_session):
    p1 = _publish(
        db_session, game_id="sb-error-1", player_id="sb-error-player-1", scheduled_start_utc=NOW, mean=8.0
    )
    p2 = _publish(
        db_session, game_id="sb-error-2", player_id="sb-error-player-2", scheduled_start_utc=NOW, mean=6.0
    )
    _grade(db_session, projection_id=p1.projection_id, result="WIN", actual_strikeouts=10)  # |10-8|=2
    _grade(db_session, projection_id=p2.projection_id, result="LOSS", actual_strikeouts=5)  # |5-6|=1

    board = build_scoreboard(db_session)

    assert board.today.projection_error_sample_size == 2
    assert board.today.mean_absolute_error == 1.5


def test_projection_error_ignores_rows_missing_either_value(db_session):
    p = _publish(
        db_session, game_id="sb-error-missing", player_id="sb-error-missing-player", scheduled_start_utc=NOW
    )
    _grade(db_session, projection_id=p.projection_id, result="VOID", actual_strikeouts=None)

    board = build_scoreboard(db_session)

    assert board.today.projection_error_sample_size == 0
    assert board.today.mean_absolute_error is None


def test_excludes_non_live_record_labels_from_every_window(db_session):
    demo = _publish(
        db_session,
        game_id="sb-demo-game",
        player_id="sb-demo-player",
        scheduled_start_utc=NOW,
        record_label="DEMO",
    )
    _grade(db_session, projection_id=demo.projection_id, result="WIN", actual_strikeouts=9)

    board = build_scoreboard(db_session)

    assert board.today.wins == 0
    assert board.all_time.wins == 0


def test_only_the_current_version_per_logical_key_counts(db_session):
    # A rerun creates a new version -- only the latest (current) one
    # should contribute, matching ledger.service's own "current" pattern.
    snapshot = _make_snapshot(db_session)
    game = _make_game(db_session, game_id="sb-version-game", scheduled_start_utc=NOW)
    player = _make_player(db_session, player_id="sb-version-player")
    decision = decide(5.5, PoissonStrikeoutDistribution(mean=8.0), [])
    v1 = publish_projection(
        db_session,
        run_id="run-v1",
        snapshot=snapshot,
        game=game,
        player_id=player.player_id,
        line=5.5,
        feature_set_version="k-features-0.1.0",
        features={},
        model_version="k-model-0.1.0",
        decision=decision,
        as_of=NOW,
    )
    db_session.flush()
    _grade(db_session, projection_id=v1.projection_id, result="LOSS")
    v2 = publish_projection(
        db_session,
        run_id="run-v2",
        snapshot=snapshot,
        game=game,
        player_id=player.player_id,
        line=5.5,
        feature_set_version="k-features-0.1.0",
        features={},
        model_version="k-model-0.1.0",
        decision=decision,
        as_of=NOW,
    )
    db_session.flush()
    _grade(db_session, projection_id=v2.projection_id, result="WIN", actual_strikeouts=9)
    db_session.flush()

    board = build_scoreboard(db_session)

    assert board.today.wins == 1
    assert board.today.losses == 0
