"""GET /api/today -- API-layer behavior: routing, serialization, the
transparency principle (every evaluated projection, not just qualified
ones), and defaulting. Orchestration/decision logic itself is tested
elsewhere; these tests only exercise the router + assembly layer."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from cassandra.config import slate_date_for
from cassandra.db.models.grading import Grade
from cassandra.db.models.identity import Game

from ._helpers import publish


def test_today_returns_all_evaluated_projections_not_just_qualified(client, db_session):
    # edge below threshold -> NO_PLAY -- must still appear on Today.
    row = publish(db_session, game_id="api-today-game-1", player_id="api-today-player-1", line=5.5, mean=5.5)
    game = db_session.get(Game, row.game_id)
    slate_date = slate_date_for(game.scheduled_start_utc)

    response = client.get("/api/today", params={"slate_date": slate_date.isoformat()})

    assert response.status_code == 200
    body = response.json()
    assert body["slate_date"] == slate_date.isoformat()
    assert body["games_count"] == 1
    assert body["no_play_count"] == 1
    assert body["qualified_count"] == 0
    assert len(body["projections"]) == 1
    assert body["projections"][0]["decision"] == "NO_PLAY"
    assert body["projections"][0]["player_name"] == "Test Player"


def test_today_includes_grade_when_available(client, db_session):
    row = publish(db_session, game_id="api-today-game-2", player_id="api-today-player-2", line=3.5, mean=8.0)
    game = db_session.get(Game, row.game_id)
    slate_date = slate_date_for(game.scheduled_start_utc)

    db_session.add(
        Grade(
            grade_id=uuid4(),
            projection_id=row.projection_id,
            graded_at=datetime.now(UTC),
            result="WIN",
            actual_strikeouts=7,
        )
    )
    db_session.flush()

    response = client.get("/api/today", params={"slate_date": slate_date.isoformat()})

    assert response.status_code == 200
    projections = response.json()["projections"]
    assert len(projections) == 1
    assert projections[0]["grade"]["result"] == "WIN"
    assert projections[0]["grade"]["actual_strikeouts"] == 7


def test_today_empty_slate_returns_zero_counts_not_an_error(client):
    response = client.get("/api/today", params={"slate_date": "2019-01-01"})

    assert response.status_code == 200
    body = response.json()
    assert body["games_count"] == 0
    assert body["projections"] == []
    assert body["qualified_count"] == 0
    assert body["no_play_count"] == 0
