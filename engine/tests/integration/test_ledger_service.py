"""Ledger service integration tests -- real Postgres. Verifies the
append-only/versioning contract end-to-end, not just in isolation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import time_machine
from sqlalchemy.dialects.postgresql import insert as pg_insert

from cassandra.db.models.identity import Game, Player
from cassandra.db.models.snapshot import Snapshot
from cassandra.decision.engine import decide
from cassandra.ledger.service import (
    current_projections_for_slate,
    latest_version,
    logical_key_for,
    publish_projection,
    recent_current_projections,
    version_history,
)
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
        status="Preview",
    )
    session.execute(stmt)
    session.flush()
    return session.get(Game, game_id)


def _make_player(session, *, player_id: str) -> None:
    stmt = pg_insert(Player).values(
        player_id=player_id,
        mlb_person_id=int(uuid.uuid4().int % 1_000_000),
        full_name=f"Test Player {player_id}",
    )
    session.execute(stmt)
    session.flush()


def test_publish_projection_creates_version_one(db_session):
    snapshot = _make_snapshot(db_session)
    game = _make_game(db_session, game_id="test-game-1", scheduled_start_utc=NOW + timedelta(hours=3))
    _make_player(db_session, player_id="test-player-1")
    decision = decide(5.5, PoissonStrikeoutDistribution(mean=8.0), [])

    row = publish_projection(
        db_session,
        run_id="run-1",
        snapshot=snapshot,
        game=game,
        player_id="test-player-1",
        line=5.5,
        feature_set_version="k-features-0.1.0",
        features={"expected_bf": 23.0},
        model_version="k-model-0.1.0",
        decision=decision,
        as_of=NOW,
    )
    db_session.flush()

    assert row.version == 1
    assert row.supersedes_projection_id is None
    assert row.decision == "OVER"
    assert row.decision_status == "QUALIFIED"
    assert row.reproducibility_hash is not None
    assert row.published_at is not None
    assert row.is_late_publication is False


def test_republishing_creates_new_version_without_mutating_first(db_session):
    snapshot = _make_snapshot(db_session)
    game = _make_game(db_session, game_id="test-game-2", scheduled_start_utc=NOW + timedelta(hours=3))
    _make_player(db_session, player_id="test-player-2")
    decision = decide(5.5, PoissonStrikeoutDistribution(mean=8.0), [])

    first = publish_projection(
        db_session,
        run_id="run-1",
        snapshot=snapshot,
        game=game,
        player_id="test-player-2",
        line=5.5,
        feature_set_version="k-features-0.1.0",
        features={"expected_bf": 23.0},
        model_version="k-model-0.1.0",
        decision=decision,
        as_of=NOW,
    )
    db_session.flush()
    first_id = first.projection_id

    second = publish_projection(
        db_session,
        run_id="run-2",
        snapshot=snapshot,
        game=game,
        player_id="test-player-2",
        line=5.5,
        feature_set_version="k-features-0.1.0",
        features={"expected_bf": 24.0},
        model_version="k-model-0.1.0",
        decision=decision,
        as_of=NOW,
    )
    db_session.flush()

    assert second.version == 2
    assert second.supersedes_projection_id == first_id
    assert second.projection_id != first_id

    logical_key = logical_key_for("test-player-2", "test-game-2")
    history = version_history(db_session, logical_key)
    assert len(history) == 2
    assert history[0].version == 2  # latest first
    assert history[1].version == 1
    assert history[1].projection_id == first_id  # first row untouched


def test_current_projections_for_slate_returns_only_latest_version(db_session):
    snapshot = _make_snapshot(db_session)
    game = _make_game(db_session, game_id="test-game-3", scheduled_start_utc=NOW + timedelta(hours=3))
    _make_player(db_session, player_id="test-player-3")
    decision = decide(5.5, PoissonStrikeoutDistribution(mean=8.0), [])

    for _ in range(3):
        publish_projection(
            db_session,
            run_id="run-x",
            snapshot=snapshot,
            game=game,
            player_id="test-player-3",
            line=5.5,
            feature_set_version="k-features-0.1.0",
            features={},
            model_version="k-model-0.1.0",
            decision=decision,
            as_of=NOW,
        )
    db_session.flush()

    current = current_projections_for_slate(db_session, ["test-game-3"])
    assert len(current) == 1
    assert current[0].version == 3


def test_current_never_returns_a_late_publication_over_an_earlier_official_one(db_session):
    # Regression for a real gap: is_late_publication was being computed
    # and stored correctly, but current_projections_for_slate/
    # recent_current_projections just took `ORDER BY version DESC`,
    # ignoring it entirely -- so a run that happened to fire after a
    # game's first pitch would silently become the displayed "current"
    # record, overriding an honest pre-lock official one. The flag was
    # recorded but never actually enforced anywhere.
    snapshot = _make_snapshot(db_session)
    game_start = NOW + timedelta(hours=1)
    game = _make_game(db_session, game_id="test-game-official", scheduled_start_utc=game_start)
    _make_player(db_session, player_id="test-player-official")
    decision = decide(5.5, PoissonStrikeoutDistribution(mean=8.0), [])

    # First run: real wall clock frozen well before first pitch.
    with time_machine.travel(game_start - timedelta(minutes=30)):
        official = publish_projection(
            db_session,
            run_id="run-official",
            snapshot=snapshot,
            game=game,
            player_id="test-player-official",
            line=5.5,
            feature_set_version="k-features-0.1.0",
            features={},
            model_version="k-model-0.1.0",
            decision=decision,
            as_of=game_start - timedelta(minutes=30),
        )
    assert official.is_late_publication is False

    # Second run: real wall clock frozen after first pitch -- e.g. a
    # retry or an extra scheduler tick that fired late.
    with time_machine.travel(game_start + timedelta(minutes=15)):
        late = publish_projection(
            db_session,
            run_id="run-late-rerun",
            snapshot=snapshot,
            game=game,
            player_id="test-player-official",
            line=6.5,  # a different line, to prove which row's data actually wins
            feature_set_version="k-features-0.1.0",
            features={},
            model_version="k-model-0.1.0",
            decision=decision,
            as_of=game_start + timedelta(minutes=15),
        )
    db_session.flush()
    assert late.version > official.version
    assert late.is_late_publication is True

    current = current_projections_for_slate(db_session, ["test-game-official"])
    assert len(current) == 1
    assert current[0].projection_id == official.projection_id
    assert current[0].line == 5.5

    recent = recent_current_projections(db_session)
    matching = [p for p in recent if p.logical_key == official.logical_key]
    assert len(matching) == 1
    assert matching[0].projection_id == official.projection_id


def test_current_falls_back_to_latest_version_when_nothing_is_official_yet(db_session):
    # A game hours out with only unpublished (evaluated, not yet
    # published) research-stage rows must still show something -- the
    # official-preference ordering must not hide a logical_key entirely
    # just because nothing official exists for it yet.
    snapshot = _make_snapshot(db_session)
    game = _make_game(
        db_session, game_id="test-game-research-only", scheduled_start_utc=NOW + timedelta(hours=5)
    )
    _make_player(db_session, player_id="test-player-research-only")
    decision = decide(5.5, PoissonStrikeoutDistribution(mean=8.0), [])

    row = publish_projection(
        db_session,
        run_id="run-research",
        snapshot=snapshot,
        game=game,
        player_id="test-player-research-only",
        line=5.5,
        feature_set_version="k-features-0.1.0",
        features={},
        model_version="k-model-0.1.0",
        decision=decision,
        as_of=NOW,
        publish=False,
    )
    db_session.flush()
    assert row.published_at is None

    current = current_projections_for_slate(db_session, ["test-game-research-only"])
    assert len(current) == 1
    assert current[0].projection_id == row.projection_id


def test_late_publication_flag_set_when_published_after_game_start(db_session):
    snapshot = _make_snapshot(db_session)
    # game already started an hour ago
    game = _make_game(db_session, game_id="test-game-late", scheduled_start_utc=NOW - timedelta(hours=1))
    _make_player(db_session, player_id="test-player-late")
    decision = decide(5.5, PoissonStrikeoutDistribution(mean=8.0), [])

    row = publish_projection(
        db_session,
        run_id="run-late",
        snapshot=snapshot,
        game=game,
        player_id="test-player-late",
        line=5.5,
        feature_set_version="k-features-0.1.0",
        features={},
        model_version="k-model-0.1.0",
        decision=decision,
        as_of=NOW,
    )
    db_session.flush()
    assert row.is_late_publication is True


def test_publish_false_does_not_set_published_at(db_session):
    snapshot = _make_snapshot(db_session)
    game = _make_game(db_session, game_id="test-game-unpub", scheduled_start_utc=NOW + timedelta(hours=3))
    _make_player(db_session, player_id="test-player-unpub")
    decision = decide(5.5, PoissonStrikeoutDistribution(mean=5.5), [])  # NO_PLAY, edge too small

    row = publish_projection(
        db_session,
        run_id="run-unpub",
        snapshot=snapshot,
        game=game,
        player_id="test-player-unpub",
        line=5.5,
        feature_set_version="k-features-0.1.0",
        features={},
        model_version="k-model-0.1.0",
        decision=decision,
        as_of=NOW,
        publish=False,
    )
    db_session.flush()
    assert row.published_at is None
    assert row.is_late_publication is False
    assert row.decision == "NO_PLAY"


def test_latest_version_none_for_unknown_logical_key(db_session):
    assert latest_version(db_session, "nope|nope|pitcher_strikeouts") is None
