"""End-to-end orchestration integration test -- real Postgres, real saved
MLB Stats API / Open-Meteo responses (mocked via respx), the actual real
2023-06-15 Blue Jays @ Orioles slate. Exercises the full INGEST -> VALIDATE
-> FREEZE -> PROJECT -> REVIEW -> PUBLISH chain, then grade_slate_run
against the real final box score, proving the whole vertical slice wires
together -- not just each stage in isolation (see the other unit/
integration tests for that)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import respx

from cassandra.adapters.final_box_scores_mlb import LIVE_FEED_BASE
from cassandra.adapters.schedule_mlb import MLB_STATS_API_BASE
from cassandra.adapters.weather_openmeteo import ARCHIVE_URL
from cassandra.db.models.pipeline import PipelineRunStage
from cassandra.identity_ids import mlb_player_id
from cassandra.orchestration.run_slate import grade_slate_run, run_slate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "mlb_api"
SLATE_DATE = datetime(2023, 6, 15).date()
KIKUCHI_MLB_ID = 579328
KIKUCHI_GAME_PK = 717753


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _gamelog_side_effect(request: httpx.Request) -> httpx.Response:
    match = re.search(r"/people/(\d+)/stats", str(request.url))
    assert match is not None
    player_id = int(match.group(1))
    if player_id == KIKUCHI_MLB_ID:
        return httpx.Response(200, json=_load("gamelog_579328_2023.json"))
    return httpx.Response(200, json={"stats": [{"splits": []}]})


def _feed_side_effect(request: httpx.Request) -> httpx.Response:
    match = re.search(r"/game/(\d+)/feed/live", str(request.url))
    assert match is not None
    game_pk = int(match.group(1))
    if game_pk == KIKUCHI_GAME_PK:
        return httpx.Response(200, json=_load("game_feed_717753.json"))
    return httpx.Response(
        200,
        json={
            "gamePk": game_pk,
            "gameData": {"status": {"abstractGameState": "Final"}},
            "liveData": {"boxscore": {"teams": {"home": {"players": {}}, "away": {"players": {}}}}},
        },
    )


def _lines_drop_dir(tmp_path: Path) -> Path:
    doc = {
        "slate_date": SLATE_DATE.isoformat(),
        "observed_at": "2023-06-15T15:00:00Z",
        "lines": [
            {
                "mlb_game_pk": KIKUCHI_GAME_PK,
                "player_mlb_id": KIKUCHI_MLB_ID,
                "market": "pitcher_strikeouts",
                "line": 5.5,
                "is_suspended": False,
            }
        ],
    }
    drop_dir = tmp_path / "lines_drops"
    drop_dir.mkdir()
    (drop_dir / "demo.json").write_text(json.dumps(doc))
    return drop_dir


@respx.mock
def test_run_slate_then_grade_slate_end_to_end(db_session, tmp_path: Path):
    respx.get(f"{MLB_STATS_API_BASE}/schedule").mock(
        return_value=httpx.Response(200, json=_load("schedule_2023-06-15.json"))
    )
    respx.route(url__regex=rf"{re.escape(MLB_STATS_API_BASE)}/people/\d+/stats").mock(
        side_effect=_gamelog_side_effect
    )
    respx.get(ARCHIVE_URL).mock(return_value=httpx.Response(200, json=_load("weather_archive_camden.json")))
    respx.route(url__regex=rf"{re.escape(LIVE_FEED_BASE)}/game/\d+/feed/live").mock(
        side_effect=_feed_side_effect
    )

    lines_drop_dir = _lines_drop_dir(tmp_path)
    # ingested_at is stamped at real wall-clock "now" during ingestion, so a
    # historical slate_date's cutoff must be "now", not the slate's
    # calendar date, or every as-of read fails its ingested_at<=cutoff
    # filter (see docs/adr/0001 and CLAUDE.md non-negotiable #2).
    cutoff_at = datetime.now(UTC) + timedelta(minutes=2)

    client = httpx.Client()
    run_result = run_slate(
        db_session, SLATE_DATE, cutoff_at, http_client=client, lines_drop_dir=lines_drop_dir, publish=True
    )
    db_session.flush()

    assert run_result.entries_frozen == 20  # 10 games x 2 probable starters
    kikuchi_id = mlb_player_id(KIKUCHI_MLB_ID)
    kikuchi_proj = next(p for p in run_result.projections_published if p.player_id == kikuchi_id)
    assert kikuchi_proj.line == 5.5
    assert kikuchi_proj.decision_status in ("QUALIFIED", "UNCERTAIN")
    assert kikuchi_proj.decision in ("OVER", "UNDER", "NO_PLAY")
    assert kikuchi_proj.reproducibility_hash is not None
    assert kikuchi_proj.published_at is not None

    # a pitcher with no market line (every other pitcher in this slate --
    # the lines drop file only covers Kikuchi) is still logged, just
    # REJECTED with no line, not silently dropped (transparency principle).
    no_line_projs = [p for p in run_result.projections_published if p.player_id != kikuchi_id]
    assert no_line_projs
    assert all(p.decision == "NO_PLAY" and p.decision_status == "REJECTED" for p in no_line_projs)
    assert all(p.line is None for p in no_line_projs)

    stages = (
        db_session.query(PipelineRunStage)
        .filter(PipelineRunStage.run_id == run_result.run_id)
        .order_by(PipelineRunStage.stage)
        .all()
    )
    stage_status = {s.stage: s.status for s in stages}
    assert stage_status["INGEST"] == "succeeded"
    assert stage_status["VALIDATE"] == "succeeded"
    assert stage_status["FREEZE"] == "succeeded"
    assert stage_status["PROJECT"] == "succeeded"
    assert stage_status["REVIEW"] == "succeeded"
    assert stage_status["PUBLISH"] == "succeeded"
    assert stage_status["GRADE"] == "skipped"

    # --- grading, once the (already-Final, real) box scores are pulled ---
    grade_result = grade_slate_run(db_session, SLATE_DATE, http_client=client)
    db_session.flush()

    kikuchi_grade = next(g for g in grade_result.grades if g.projection_id == kikuchi_proj.projection_id)
    assert kikuchi_grade.actual_strikeouts == 7  # real recorded outcome for this game
    line = float(kikuchi_proj.line)
    beat_the_line = line < 7 if kikuchi_proj.decision == "OVER" else line > 7
    expected_result = "WIN" if beat_the_line else "LOSS"
    assert kikuchi_grade.result == expected_result
    assert kikuchi_grade.result in ("WIN", "LOSS")  # 7 != 5.5, so never a push

    # the no-line pitchers are NO_PLAY -- they still grade, honestly, as
    # NO_PLAY regardless of what actually happened in the game.
    no_line_grades = [
        g for g in grade_result.grades if g.projection_id in {p.projection_id for p in no_line_projs}
    ]
    assert no_line_grades
    assert all(g.result == "NO_PLAY" for g in no_line_grades)

    grade_stage = (
        db_session.query(PipelineRunStage)
        .filter(PipelineRunStage.run_id == grade_result.run_id, PipelineRunStage.stage == "GRADE")
        .one()
    )
    assert grade_stage.status == "succeeded"
