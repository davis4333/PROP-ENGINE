"""grading/tracker.py against a real Postgres session -- the resettable
Admin win/loss counter. Grade rows are inserted directly (not via
grade_projection()) for exact control over `result`/`graded_at`, since
these tests are about tracker.py's own aggregation/filtering logic, not
the grading pipeline itself (already covered by test_grading_service.py).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert as pg_insert

from cassandra.db.models.grading import Grade
from cassandra.db.models.identity import Game, Player
from cassandra.db.models.snapshot import Snapshot
from cassandra.decision.engine import decide
from cassandra.grading.tracker import latest_tracker_reset, reset_tracker, tracker_summary
from cassandra.ledger.service import publish_projection
from cassandra.models.baseline import PoissonStrikeoutDistribution

NOW = datetime.now(UTC)


def _make_snapshot(session) -> Snapshot:
    snap = Snapshot(slate_date=NOW.date(), cutoff_at=NOW, status="frozen")
    session.add(snap)
    session.flush()
    return snap


def _make_game(session, *, game_id: str) -> Game:
    stmt = pg_insert(Game).values(
        game_id=game_id,
        mlb_game_pk=int(uuid.uuid4().int % 1_000_000),
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


def _make_player(session, *, player_id: str) -> Player:
    stmt = pg_insert(Player).values(
        player_id=player_id, mlb_person_id=int(uuid.uuid4().int % 1_000_000), full_name=f"Test {player_id}"
    )
    session.execute(stmt)
    session.flush()
    return session.get(Player, player_id)


def _publish(session, *, game_id: str, player_id: str, record_label: str = "LIVE"):
    snapshot = _make_snapshot(session)
    game = _make_game(session, game_id=game_id)
    player = _make_player(session, player_id=player_id)
    decision = decide(5.5, PoissonStrikeoutDistribution(mean=8.0), [])
    row = publish_projection(
        session,
        run_id="run-tracker",
        snapshot=snapshot,
        game=game,
        player_id=player.player_id,
        line=5.5,
        feature_set_version="k-features-0.1.0",
        features={},
        model_version="k-model-0.1.0",
        decision=decision,
        as_of=NOW,
        record_label=record_label,
    )
    session.flush()
    return row


def _grade(session, *, projection_id: str, result: str, graded_at: datetime) -> Grade:
    row = Grade(grade_id=uuid.uuid4(), projection_id=projection_id, graded_at=graded_at, result=result)
    session.add(row)
    session.flush()
    return row


def test_empty_tracker_has_zero_everything(db_session):
    summary = tracker_summary(db_session)
    assert summary.wins == 0
    assert summary.losses == 0
    assert summary.pushes == 0
    assert summary.voids == 0
    assert summary.no_plays == 0
    assert summary.win_rate is None
    assert summary.last_reset_by is None


def test_counts_wins_losses_pushes_voids_no_plays(db_session):
    p1 = _publish(db_session, game_id="tracker-game-1", player_id="tracker-player-1")
    p2 = _publish(db_session, game_id="tracker-game-2", player_id="tracker-player-2")
    p3 = _publish(db_session, game_id="tracker-game-3", player_id="tracker-player-3")
    p4 = _publish(db_session, game_id="tracker-game-4", player_id="tracker-player-4")
    p5 = _publish(db_session, game_id="tracker-game-5", player_id="tracker-player-5")
    _grade(db_session, projection_id=p1.projection_id, result="WIN", graded_at=NOW)
    _grade(db_session, projection_id=p2.projection_id, result="WIN", graded_at=NOW)
    _grade(db_session, projection_id=p3.projection_id, result="LOSS", graded_at=NOW)
    _grade(db_session, projection_id=p4.projection_id, result="PUSH", graded_at=NOW)
    _grade(db_session, projection_id=p5.projection_id, result="VOID", graded_at=NOW)

    summary = tracker_summary(db_session)

    assert summary.wins == 2
    assert summary.losses == 1
    assert summary.pushes == 1
    assert summary.voids == 1
    assert summary.win_rate == 2 / 3


def test_only_the_current_grade_per_projection_counts(db_session):
    # A correction (later graded_at) supersedes the original -- only the
    # latest should count, matching current_grades_for_projections'
    # "current" derivation elsewhere.
    p1 = _publish(db_session, game_id="tracker-game-correction", player_id="tracker-player-correction")
    _grade(db_session, projection_id=p1.projection_id, result="LOSS", graded_at=NOW)
    _grade(db_session, projection_id=p1.projection_id, result="WIN", graded_at=NOW + timedelta(hours=1))

    summary = tracker_summary(db_session)

    assert summary.wins == 1
    assert summary.losses == 0


def test_excludes_non_live_record_labels(db_session):
    backtest = _publish(
        db_session,
        game_id="tracker-game-backtest",
        player_id="tracker-player-backtest",
        record_label="BACKTEST",
    )
    _grade(db_session, projection_id=backtest.projection_id, result="WIN", graded_at=NOW)

    summary = tracker_summary(db_session)

    assert summary.wins == 0


def test_reset_excludes_grades_before_the_reset(db_session):
    before = _publish(db_session, game_id="tracker-game-before", player_id="tracker-player-before")
    _grade(db_session, projection_id=before.projection_id, result="LOSS", graded_at=NOW)

    reset_event = reset_tracker(db_session, operator="tyler")

    after = _publish(db_session, game_id="tracker-game-after", player_id="tracker-player-after")
    _grade(db_session, projection_id=after.projection_id, result="WIN", graded_at=NOW + timedelta(hours=1))

    summary = tracker_summary(db_session)

    assert summary.wins == 1
    assert summary.losses == 0
    assert summary.tracker_started_at == reset_event.created_at
    assert summary.last_reset_by == "tyler"


def test_a_second_reset_supersedes_the_first(db_session):
    # reset_tracker() relies on AuditEvent.created_at's server_default --
    # Postgres's now() is frozen per-transaction, so two resets issued
    # inside the SAME transaction (as reset_tracker(); reset_tracker()
    # would be here) tie on created_at and can't be told apart, exactly
    # like the bug fixed for model_registry_events' occurred_at. This
    # isn't reachable via the real POST /api/admin/tracker/reset endpoint
    # -- each HTTP request gets its own session/transaction, so two real
    # resets always get genuinely distinct now() values -- so this test
    # constructs the two events directly with explicit, distinct
    # created_at values (real usage's actual shape) rather than calling
    # reset_tracker() twice in one transaction (an unrealistic shape that
    # would spuriously fail on the tie).
    from cassandra.db.models.audit import AuditEvent
    from cassandra.grading.tracker import TRACKER_RESET_EVENT_TYPE

    first_at = NOW
    second_at = NOW + timedelta(minutes=5)
    db_session.add(
        AuditEvent(
            event_type=TRACKER_RESET_EVENT_TYPE,
            entity_type="tracker",
            actor="tyler",
            created_at=first_at,
        )
    )
    db_session.add(
        AuditEvent(
            event_type=TRACKER_RESET_EVENT_TYPE,
            entity_type="tracker",
            actor="admin-two",
            created_at=second_at,
        )
    )
    db_session.flush()

    summary = tracker_summary(db_session)

    assert summary.last_reset_by == "admin-two"
    assert summary.tracker_started_at == second_at


def test_reset_tracker_never_touches_any_grade_row(db_session):
    p1 = _publish(db_session, game_id="tracker-game-immutable", player_id="tracker-player-immutable")
    grade = _grade(db_session, projection_id=p1.projection_id, result="LOSS", graded_at=NOW)

    reset_tracker(db_session, operator="tyler")

    reloaded = db_session.get(Grade, grade.grade_id)
    assert reloaded is not None
    assert reloaded.result == "LOSS"


def test_latest_tracker_reset_is_none_before_any_reset(db_session):
    assert latest_tracker_reset(db_session) is None
