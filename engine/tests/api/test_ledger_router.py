"""GET /api/ledger and /api/ledger/{projection_id} -- honest results
ledger. Losses must appear exactly like wins (CLAUDE.md non-negotiable
#6); version history must show every version, not just the latest."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from cassandra.config import slate_date_for
from cassandra.db.models.grading import Grade
from cassandra.db.models.identity import Game

from ._helpers import publish


def test_ledger_shows_a_loss_exactly_like_a_win(client, db_session):
    row = publish(
        db_session, game_id="api-ledger-game-1", player_id="api-ledger-player-1", line=3.5, mean=8.0
    )
    game = db_session.get(Game, row.game_id)
    slate_date = slate_date_for(game.scheduled_start_utc)

    db_session.add(
        Grade(
            grade_id=uuid4(),
            projection_id=row.projection_id,
            graded_at=datetime.now(UTC),
            result="LOSS",
            actual_strikeouts=1,
        )
    )
    db_session.flush()

    response = client.get("/api/ledger", params={"slate_date": slate_date.isoformat()})

    assert response.status_code == 200
    entries = response.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["grade"]["result"] == "LOSS"


def test_ledger_without_slate_date_returns_recent_entries_across_slates(client, db_session):
    publish(db_session, game_id="api-ledger-game-2", player_id="api-ledger-player-2")
    publish(db_session, game_id="api-ledger-game-3", player_id="api-ledger-player-3")

    response = client.get("/api/ledger")

    assert response.status_code == 200
    body = response.json()
    assert body["slate_date"] is None
    assert len(body["entries"]) >= 2


def test_ledger_projection_history_returns_all_versions(client, db_session):
    first = publish(db_session, game_id="api-ledger-game-4", player_id="api-ledger-player-4", line=5.5)
    second = publish(db_session, game_id="api-ledger-game-4", player_id="api-ledger-player-4", line=5.5)

    response = client.get(f"/api/ledger/{second.projection_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["logical_key"] == first.logical_key
    versions = {v["version"] for v in body["versions"]}
    assert versions == {1, 2}


def test_ledger_projection_history_404_for_unknown_id(client):
    response = client.get("/api/ledger/does-not-exist")

    assert response.status_code == 404
