"""GET /api/today -- API-layer behavior: routing, serialization, the
transparency principle (every evaluated projection, not just qualified
ones), and defaulting. Orchestration/decision logic itself is tested
elsewhere; these tests only exercise the router + assembly layer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert as pg_insert

from cassandra.config import slate_date_for
from cassandra.db.models.features import FeatureSet, FeatureValue
from cassandra.db.models.grading import Grade
from cassandra.db.models.identity import Game
from cassandra.db.models.raw import RawLine
from cassandra.db.models.sources import Source
from cassandra.decision.engine import decide
from cassandra.ledger.service import publish_projection
from cassandra.models.baseline import PoissonStrikeoutDistribution

from ._helpers import NOW, make_game, make_player, make_snapshot, publish


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


def test_today_sorts_qualified_picks_before_no_plays(client, db_session):
    # A clear-edge QUALIFIED pick and a no-line REJECTED row on the same
    # slate -- regardless of insertion order, the qualified pick with a
    # real tradeable edge must render first.
    rejected = publish(
        db_session, game_id="api-today-sort-1", player_id="api-today-sort-player-1", line=None, mean=6.0
    )
    qualified = publish(
        db_session, game_id="api-today-sort-2", player_id="api-today-sort-player-2", line=3.5, mean=9.0
    )
    game = db_session.get(Game, qualified.game_id)
    slate_date = slate_date_for(game.scheduled_start_utc)

    response = client.get("/api/today", params={"slate_date": slate_date.isoformat()})

    assert response.status_code == 200
    projections = response.json()["projections"]
    assert len(projections) == 2
    assert projections[0]["projection_id"] == qualified.projection_id
    assert projections[0]["decision_status"] == "QUALIFIED"
    assert projections[1]["projection_id"] == rejected.projection_id
    assert projections[1]["decision_status"] == "REJECTED"


def test_today_qualified_pick_carries_edge_why_and_line_provenance(client, db_session):
    # A real end-to-end wiring check for the "why Cassandra likes this
    # play" / edge / line-provenance enrichment (api/assembly.py +
    # decision/explain.py): seeds an actual RawLine and FeatureValue --
    # the same tables the live pipeline writes -- and confirms the API
    # re-derives from them, not from anything invented at request time.
    source_id = "test-today-explain-source"
    db_session.execute(
        pg_insert(Source)
        .values(source_id=source_id, name=source_id, kind="lines")
        .on_conflict_do_nothing(index_elements=[Source.source_id])
    )
    snapshot = make_snapshot(db_session)
    game = make_game(db_session, game_id="api-today-explain-game")
    player = make_player(db_session, player_id="api-today-explain-player")

    line_time = NOW - timedelta(hours=2)
    db_session.add(
        RawLine(
            source_id=source_id,
            mlb_game_pk=game.mlb_game_pk,
            player_mlb_id=player.mlb_person_id,
            market="pitcher_strikeouts",
            line=5.5,
            observed_at=line_time,
            ingested_at=line_time,
            payload={},
        )
    )
    db_session.execute(
        pg_insert(FeatureSet)
        .values(feature_set_version="k-features-0.1.0")
        .on_conflict_do_nothing(index_elements=[FeatureSet.feature_set_version])
    )
    features = {
        "expected_bf": 24.0,
        "expected_bf_tier": "recent_weighted",
        "expected_bf_starts_used": 6,
        "recent_k_rate": 0.30,
        "recent_k_rate_tier": "recent_weighted",
        "recent_k_rate_starts_used": 6,
        "park_k_factor": 1.0,
        "weather_adjustment": 1.0,
        "role_stability_flag": False,
    }
    decision = decide(5.5, PoissonStrikeoutDistribution(mean=9.0), [])
    row = publish_projection(
        db_session,
        run_id="run-api-explain-test",
        snapshot=snapshot,
        game=game,
        player_id=player.player_id,
        line=5.5,
        feature_set_version="k-features-0.1.0",
        features=features,
        model_version="k-model-0.1.0",
        decision=decision,
        as_of=NOW,
    )
    db_session.add(
        FeatureValue(
            snapshot_id=snapshot.snapshot_id,
            player_id=player.player_id,
            game_id=game.game_id,
            feature_set_version="k-features-0.1.0",
            features=features,
        )
    )
    db_session.flush()
    slate_date = slate_date_for(game.scheduled_start_utc)

    response = client.get("/api/today", params={"slate_date": slate_date.isoformat()})

    assert response.status_code == 200
    projections = response.json()["projections"]
    matching = [p for p in projections if p["projection_id"] == row.projection_id]
    assert len(matching) == 1
    out = matching[0]

    assert out["decision"] == "OVER"
    assert out["decision_status"] == "QUALIFIED"
    assert out["edge"] is not None
    assert out["edge"] > 0
    assert out["line_source"] == source_id
    assert out["line_observed_at"] is not None
    assert out["why"] != []
    assert any("9.00" in b and "5.5" in b for b in out["why"])
    assert any("30.0%" in b for b in out["why"])
    assert out["risks"] == []


def test_today_no_play_has_no_why_bullets_but_explains_the_rejection(client, db_session):
    row = publish(
        db_session,
        game_id="api-today-explain-nolines",
        player_id="api-today-explain-noline-player",
        line=None,
    )
    game = db_session.get(Game, row.game_id)
    slate_date = slate_date_for(game.scheduled_start_utc)

    response = client.get("/api/today", params={"slate_date": slate_date.isoformat()})

    assert response.status_code == 200
    projections = response.json()["projections"]
    matching = [p for p in projections if p["projection_id"] == row.projection_id]
    assert len(matching) == 1
    out = matching[0]
    assert out["decision"] == "NO_PLAY"
    assert out["why"] == []
    assert out["risks"] != []
    assert out["edge"] is None
    assert out["line_source"] is None


def test_today_empty_slate_returns_zero_counts_not_an_error(client):
    response = client.get("/api/today", params={"slate_date": "2019-01-01"})

    assert response.status_code == 200
    body = response.json()
    assert body["games_count"] == 0
    assert body["projections"] == []
    assert body["qualified_count"] == 0
    assert body["no_play_count"] == 0
