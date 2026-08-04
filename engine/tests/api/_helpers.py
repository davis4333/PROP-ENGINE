"""Shared setup helpers for API tests -- not a test module itself (no
`test_` functions), just plain builders reused across test_today_router.py
/ test_ledger_router.py."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert as pg_insert

from cassandra.db.models.identity import Game, Player
from cassandra.db.models.snapshot import Snapshot
from cassandra.decision.engine import decide
from cassandra.ledger.service import publish_projection
from cassandra.models.baseline import PoissonStrikeoutDistribution

NOW = datetime.now(UTC)


def make_snapshot(session) -> Snapshot:
    snap = Snapshot(slate_date=NOW.date(), cutoff_at=NOW, status="frozen")
    session.add(snap)
    session.flush()
    return snap


def make_game(session, *, game_id: str, scheduled_start_utc: datetime | None = None) -> Game:
    stmt = pg_insert(Game).values(
        game_id=game_id,
        mlb_game_pk=int(uuid.uuid4().int % 1_000_000),
        game_date=NOW,
        scheduled_start_utc=scheduled_start_utc or (NOW + timedelta(hours=3)),
        home_team_id=None,
        away_team_id=None,
        venue_id=None,
        status="Preview",
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=[Game.game_id])
    session.execute(stmt)
    session.flush()
    return session.get(Game, game_id)


def make_player(session, *, player_id: str, full_name: str = "Test Player") -> Player:
    stmt = pg_insert(Player).values(
        player_id=player_id, mlb_person_id=int(uuid.uuid4().int % 1_000_000), full_name=full_name
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=[Player.player_id])
    session.execute(stmt)
    session.flush()
    return session.get(Player, player_id)


def publish(
    session, *, game_id: str, player_id: str, line: float = 5.5, mean: float = 8.0, publish: bool = True
):
    snapshot = make_snapshot(session)
    game = make_game(session, game_id=game_id)
    make_player(session, player_id=player_id)
    decision = decide(line, PoissonStrikeoutDistribution(mean=mean), [])
    row = publish_projection(
        session,
        run_id="run-api-test",
        snapshot=snapshot,
        game=game,
        player_id=player_id,
        line=line,
        feature_set_version="k-features-0.1.0",
        features={"expected_bf": 23.0},
        model_version="k-model-0.1.0",
        decision=decision,
        as_of=NOW,
        publish=publish,
    )
    session.flush()
    return row
