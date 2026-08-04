"""Grading service integration tests -- real Postgres. Verifies the
append-only/honest-grading contract (ADR 0007, CLAUDE.md non-negotiable #6:
losses are never deleted)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert as pg_insert

from cassandra.db.models.identity import Game, Player
from cassandra.db.models.raw import RawFinalBoxScore
from cassandra.db.models.snapshot import Snapshot
from cassandra.db.models.sources import Source
from cassandra.decision.engine import decide
from cassandra.grading.service import (
    current_grade_for_projection,
    current_grades_for_projections,
    grade_projection,
    grade_slate,
    latest_final_box_score,
)
from cassandra.ledger.service import current_projections_for_slate, publish_projection
from cassandra.models.baseline import PoissonStrikeoutDistribution

NOW = datetime.now(UTC)


def _make_snapshot(session) -> Snapshot:
    snap = Snapshot(slate_date=NOW.date(), cutoff_at=NOW, status="frozen")
    session.add(snap)
    session.flush()
    return snap


def _make_source(session, *, source_id: str) -> Source:
    stmt = pg_insert(Source).values(source_id=source_id, name=source_id, kind="pitcher_stats")
    session.execute(stmt)
    session.flush()
    return session.get(Source, source_id)


def _make_game(session, *, game_id: str, mlb_game_pk: int) -> Game:
    stmt = pg_insert(Game).values(
        game_id=game_id,
        mlb_game_pk=mlb_game_pk,
        game_date=NOW,
        scheduled_start_utc=NOW - timedelta(hours=3),
        home_team_id=None,
        away_team_id=None,
        venue_id=None,
        status="Final",
    )
    session.execute(stmt)
    session.flush()
    return session.get(Game, game_id)


def _make_player(session, *, player_id: str, mlb_person_id: int) -> Player:
    stmt = pg_insert(Player).values(
        player_id=player_id, mlb_person_id=mlb_person_id, full_name=f"Test {player_id}"
    )
    session.execute(stmt)
    session.flush()
    return session.get(Player, player_id)


def _make_box_score(
    session,
    *,
    source_id: str,
    mlb_game_pk: int,
    player_mlb_id: int,
    strikeouts: int | None,
    status: str = "Final",
    ingested_at: datetime | None = None,
) -> RawFinalBoxScore:
    # Postgres `now()` (this model's ingested_at server_default) is
    # evaluated once per transaction, not per statement -- since every
    # test here runs inside one transaction (see conftest.py's db_session
    # fixture), two box scores for the same outing would otherwise tie on
    # ingested_at. Tests that insert a correction must pass explicit,
    # distinct ingested_at values.
    row = RawFinalBoxScore(
        raw_id=uuid.uuid4(),
        source_id=source_id,
        mlb_game_pk=mlb_game_pk,
        player_mlb_id=player_mlb_id,
        strikeouts_recorded=strikeouts,
        innings_pitched=6.0,
        pitch_count=95,
        game_status=status,
        observed_at=NOW,
        ingested_at=ingested_at or NOW,
        payload={"strikeouts": strikeouts, "status": status},
    )
    session.add(row)
    session.flush()
    return row


def _publish(session, *, snapshot, game, player_id, line, mean, publish=True):
    decision = decide(line, PoissonStrikeoutDistribution(mean=mean), [])
    row = publish_projection(
        session,
        run_id="run-grade",
        snapshot=snapshot,
        game=game,
        player_id=player_id,
        line=line,
        feature_set_version="k-features-0.1.0",
        features={},
        model_version="k-model-0.1.0",
        decision=decision,
        as_of=NOW,
        publish=publish,
    )
    session.flush()
    return row


def test_over_decision_wins_when_actual_beats_line(db_session):
    snapshot = _make_snapshot(db_session)
    source = _make_source(db_session, source_id="src-box-1")
    game = _make_game(db_session, game_id="grade-game-1", mlb_game_pk=111)
    player = _make_player(db_session, player_id="grade-player-1", mlb_person_id=1001)
    projection = _publish(
        db_session, snapshot=snapshot, game=game, player_id=player.player_id, line=5.5, mean=8.0
    )
    assert projection.decision == "OVER"

    _make_box_score(db_session, source_id=source.source_id, mlb_game_pk=111, player_mlb_id=1001, strikeouts=7)

    grade = grade_projection(db_session, projection, run_id="run-grade")
    db_session.flush()

    assert grade is not None
    assert grade.result == "WIN"
    assert grade.actual_strikeouts == 7


def test_over_decision_loses_when_actual_below_line(db_session):
    snapshot = _make_snapshot(db_session)
    source = _make_source(db_session, source_id="src-box-2")
    game = _make_game(db_session, game_id="grade-game-2", mlb_game_pk=112)
    player = _make_player(db_session, player_id="grade-player-2", mlb_person_id=1002)
    projection = _publish(
        db_session, snapshot=snapshot, game=game, player_id=player.player_id, line=5.5, mean=8.0
    )
    assert projection.decision == "OVER"

    _make_box_score(db_session, source_id=source.source_id, mlb_game_pk=112, player_mlb_id=1002, strikeouts=3)

    grade = grade_projection(db_session, projection, run_id="run-grade")
    db_session.flush()

    assert grade is not None
    assert grade.result == "LOSS"
    assert grade.actual_strikeouts == 3


def test_whole_number_line_exact_match_is_push(db_session):
    snapshot = _make_snapshot(db_session)
    source = _make_source(db_session, source_id="src-box-3")
    game = _make_game(db_session, game_id="grade-game-3", mlb_game_pk=113)
    player = _make_player(db_session, player_id="grade-player-3", mlb_person_id=1003)
    projection = _publish(
        db_session, snapshot=snapshot, game=game, player_id=player.player_id, line=6.0, mean=8.0
    )
    assert projection.decision == "OVER"

    _make_box_score(db_session, source_id=source.source_id, mlb_game_pk=113, player_mlb_id=1003, strikeouts=6)

    grade = grade_projection(db_session, projection, run_id="run-grade")
    db_session.flush()

    assert grade is not None
    assert grade.result == "PUSH"


def test_no_play_decision_grades_as_no_play_regardless_of_outcome(db_session):
    snapshot = _make_snapshot(db_session)
    source = _make_source(db_session, source_id="src-box-4")
    game = _make_game(db_session, game_id="grade-game-4", mlb_game_pk=114)
    player = _make_player(db_session, player_id="grade-player-4", mlb_person_id=1004)
    projection = _publish(
        db_session, snapshot=snapshot, game=game, player_id=player.player_id, line=5.5, mean=5.5
    )
    assert projection.decision == "NO_PLAY"

    _make_box_score(db_session, source_id=source.source_id, mlb_game_pk=114, player_mlb_id=1004, strikeouts=9)

    grade = grade_projection(db_session, projection, run_id="run-grade")
    db_session.flush()

    assert grade is not None
    assert grade.result == "NO_PLAY"


def test_missing_strikeout_stat_on_final_box_score_is_void(db_session):
    snapshot = _make_snapshot(db_session)
    source = _make_source(db_session, source_id="src-box-5")
    game = _make_game(db_session, game_id="grade-game-5", mlb_game_pk=115)
    player = _make_player(db_session, player_id="grade-player-5", mlb_person_id=1005)
    projection = _publish(
        db_session, snapshot=snapshot, game=game, player_id=player.player_id, line=5.5, mean=8.0
    )

    # scratched start: game is Final but this pitcher never recorded a stat
    _make_box_score(
        db_session, source_id=source.source_id, mlb_game_pk=115, player_mlb_id=1005, strikeouts=None
    )

    grade = grade_projection(db_session, projection, run_id="run-grade")
    db_session.flush()

    assert grade is not None
    assert grade.result == "VOID"
    assert grade.actual_strikeouts is None


def test_unpublished_projection_is_not_graded(db_session):
    snapshot = _make_snapshot(db_session)
    source = _make_source(db_session, source_id="src-box-6")
    game = _make_game(db_session, game_id="grade-game-6", mlb_game_pk=116)
    player = _make_player(db_session, player_id="grade-player-6", mlb_person_id=1006)
    projection = _publish(
        db_session,
        snapshot=snapshot,
        game=game,
        player_id=player.player_id,
        line=5.5,
        mean=8.0,
        publish=False,
    )
    assert projection.published_at is None

    _make_box_score(db_session, source_id=source.source_id, mlb_game_pk=116, player_mlb_id=1006, strikeouts=7)

    grade = grade_projection(db_session, projection, run_id="run-grade")
    assert grade is None


def test_non_final_box_score_is_refused(db_session):
    snapshot = _make_snapshot(db_session)
    source = _make_source(db_session, source_id="src-box-7")
    game = _make_game(db_session, game_id="grade-game-7", mlb_game_pk=117)
    player = _make_player(db_session, player_id="grade-player-7", mlb_person_id=1007)
    projection = _publish(
        db_session, snapshot=snapshot, game=game, player_id=player.player_id, line=5.5, mean=8.0
    )

    _make_box_score(
        db_session,
        source_id=source.source_id,
        mlb_game_pk=117,
        player_mlb_id=1007,
        strikeouts=7,
        status="InProgress",
    )

    assert latest_final_box_score(db_session, 117, 1007) is None
    grade = grade_projection(db_session, projection, run_id="run-grade")
    assert grade is None


def test_regrading_without_new_data_does_not_duplicate(db_session):
    snapshot = _make_snapshot(db_session)
    source = _make_source(db_session, source_id="src-box-8")
    game = _make_game(db_session, game_id="grade-game-8", mlb_game_pk=118)
    player = _make_player(db_session, player_id="grade-player-8", mlb_person_id=1008)
    projection = _publish(
        db_session, snapshot=snapshot, game=game, player_id=player.player_id, line=5.5, mean=8.0
    )

    _make_box_score(db_session, source_id=source.source_id, mlb_game_pk=118, player_mlb_id=1008, strikeouts=7)

    first = grade_projection(db_session, projection, run_id="run-grade-1")
    db_session.flush()
    second = grade_projection(db_session, projection, run_id="run-grade-2")
    db_session.flush()

    assert first is not None
    assert second is not None
    assert first.grade_id == second.grade_id


def test_correction_appends_new_grade_without_mutating_first(db_session):
    snapshot = _make_snapshot(db_session)
    source = _make_source(db_session, source_id="src-box-9")
    game = _make_game(db_session, game_id="grade-game-9", mlb_game_pk=119)
    player = _make_player(db_session, player_id="grade-player-9", mlb_person_id=1009)
    projection = _publish(
        db_session, snapshot=snapshot, game=game, player_id=player.player_id, line=5.5, mean=8.0
    )

    _make_box_score(
        db_session,
        source_id=source.source_id,
        mlb_game_pk=119,
        player_mlb_id=1009,
        strikeouts=3,
        ingested_at=NOW,
    )
    first = grade_projection(db_session, projection, run_id="run-grade-1")
    db_session.flush()
    assert first is not None
    assert first.result == "LOSS"
    first_id = first.grade_id

    # official scorer correction: a later-ingested Final row with a
    # different strikeout count
    _make_box_score(
        db_session,
        source_id=source.source_id,
        mlb_game_pk=119,
        player_mlb_id=1009,
        strikeouts=7,
        ingested_at=NOW + timedelta(seconds=1),
    )
    second = grade_projection(db_session, projection, run_id="run-grade-2")
    db_session.flush()

    assert second is not None
    assert second.result == "WIN"
    assert second.grade_id != first_id

    current = current_grade_for_projection(db_session, projection.projection_id)
    assert current is not None
    assert current.grade_id == second.grade_id


def test_grade_slate_grades_every_current_projection_for_the_slate(db_session):
    snapshot = _make_snapshot(db_session)
    source = _make_source(db_session, source_id="src-box-10")

    win_game = _make_game(db_session, game_id="grade-game-win", mlb_game_pk=201)
    win_player = _make_player(db_session, player_id="grade-player-win", mlb_person_id=2001)
    win_proj = _publish(
        db_session, snapshot=snapshot, game=win_game, player_id=win_player.player_id, line=5.5, mean=8.0
    )
    _make_box_score(db_session, source_id=source.source_id, mlb_game_pk=201, player_mlb_id=2001, strikeouts=8)

    loss_game = _make_game(db_session, game_id="grade-game-loss", mlb_game_pk=202)
    loss_player = _make_player(db_session, player_id="grade-player-loss", mlb_person_id=2002)
    loss_proj = _publish(
        db_session, snapshot=snapshot, game=loss_game, player_id=loss_player.player_id, line=5.5, mean=8.0
    )
    _make_box_score(db_session, source_id=source.source_id, mlb_game_pk=202, player_mlb_id=2002, strikeouts=2)

    push_game = _make_game(db_session, game_id="grade-game-push", mlb_game_pk=203)
    push_player = _make_player(db_session, player_id="grade-player-push", mlb_person_id=2003)
    push_proj = _publish(
        db_session, snapshot=snapshot, game=push_game, player_id=push_player.player_id, line=6.0, mean=8.0
    )
    _make_box_score(db_session, source_id=source.source_id, mlb_game_pk=203, player_mlb_id=2003, strikeouts=6)

    db_session.flush()

    game_ids = [win_game.game_id, loss_game.game_id, push_game.game_id]
    current = current_projections_for_slate(db_session, game_ids)
    assert {p.projection_id for p in current} == {
        win_proj.projection_id,
        loss_proj.projection_id,
        push_proj.projection_id,
    }

    graded = grade_slate(db_session, current, run_id="run-slate-grade")
    db_session.flush()

    results = {g.projection_id: g.result for g in graded}
    assert results[win_proj.projection_id] == "WIN"
    assert results[loss_proj.projection_id] == "LOSS"
    assert results[push_proj.projection_id] == "PUSH"

    fetched = current_grades_for_projections(db_session, list(results))
    assert {g.result for g in fetched} == {"WIN", "LOSS", "PUSH"}
