#!/usr/bin/env python3
"""Seeds and runs the fixture demo slate (2023-06-15, a real historical
MLB slate) end to end: ingest, freeze, project, decide, publish, grade.

Live MLB Stats API network calls can't retroactively serve
`probablePitcher` data for an already-`Final` historical game (confirmed
empirically), so this replays the real saved API responses under
`engine/tests/fixtures/mlb_api/` via `respx` instead of hitting the
network -- deterministic and offline. See
`engine/tests/fixtures/demo_slate/README.md` for exactly which pitchers
were hand-picked and why, and the WIN/LOSS/PUSH/NO_PLAY outcomes to
expect.

Usage:
    make db-up   # or otherwise have Postgres reachable at $DATABASE_URL
    make install
    python scripts/seed_demo_slate.py
    # or: python scripts/seed_demo_slate.py --dry-run   (rolls back, no commit)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "engine" / "src"))

import httpx
import respx
from cassandra.adapters.final_box_scores_mlb import LIVE_FEED_BASE
from cassandra.adapters.schedule_mlb import MLB_STATS_API_BASE
from cassandra.adapters.weather_openmeteo import ARCHIVE_URL
from cassandra.db.session import SessionLocal
from cassandra.grading.service import current_grade_for_projection
from cassandra.ledger.service import current_projections_for_slate
from cassandra.orchestration.run_slate import grade_slate_run, run_slate
from cassandra.pit.snapshot_builder import games_for_slate_date

MLB_API_FIXTURES = REPO_ROOT / "engine" / "tests" / "fixtures" / "mlb_api"
DEMO_FIXTURES = REPO_ROOT / "engine" / "tests" / "fixtures" / "demo_slate"
SLATE_DATE = date(2023, 6, 15)
KNOWN_GAME_FEEDS = {717753, 717755}


def _load(name: str) -> dict:
    return json.loads((MLB_API_FIXTURES / name).read_text())


def _gamelog_side_effect(request: httpx.Request) -> httpx.Response:
    match = re.search(r"/people/(\d+)/stats", str(request.url))
    assert match is not None
    player_id = match.group(1)
    fixture = MLB_API_FIXTURES / f"gamelog_{player_id}_2023.json"
    if fixture.exists():
        return httpx.Response(200, json=json.loads(fixture.read_text()))
    return httpx.Response(200, json={"stats": [{"splits": []}]})


def _feed_side_effect(request: httpx.Request) -> httpx.Response:
    match = re.search(r"/game/(\d+)/feed/live", str(request.url))
    assert match is not None
    game_pk = int(match.group(1))
    if game_pk in KNOWN_GAME_FEEDS:
        return httpx.Response(200, json=_load(f"game_feed_{game_pk}.json"))
    return httpx.Response(
        200,
        json={
            "gamePk": game_pk,
            "gameData": {"status": {"abstractGameState": "Final"}},
            "liveData": {
                "boxscore": {
                    "teams": {"home": {"players": {}}, "away": {"players": {}}}
                }
            },
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Roll back instead of committing."
    )
    args = parser.parse_args()

    with respx.mock:
        respx.get(f"{MLB_STATS_API_BASE}/schedule").mock(
            return_value=httpx.Response(200, json=_load("schedule_2023-06-15.json"))
        )
        respx.route(
            url__regex=rf"{re.escape(MLB_STATS_API_BASE)}/people/\d+/stats"
        ).mock(side_effect=_gamelog_side_effect)
        respx.get(ARCHIVE_URL).mock(
            return_value=httpx.Response(200, json=_load("weather_archive_camden.json"))
        )
        respx.route(url__regex=rf"{re.escape(LIVE_FEED_BASE)}/game/\d+/feed/live").mock(
            side_effect=_feed_side_effect
        )

        session = SessionLocal()
        client = httpx.Client()
        try:
            cutoff_at = datetime.now(UTC) + timedelta(minutes=2)
            run_result = run_slate(
                session,
                SLATE_DATE,
                cutoff_at,
                http_client=client,
                lines_drop_dir=DEMO_FIXTURES,
                publish=True,
                # Never "LIVE" -- this is a fixture replay, not a real
                # pipeline run, and must never be mistaken for one on any
                # page that reads the projections table (see
                # db/models/projection.py's RECORD_LABELS).
                record_label="DEMO",
            )
            print(f"run_slate: run_id={run_result.run_id}")
            print(
                f"  {run_result.entries_frozen} pitcher-slate entries frozen "
                f"({run_result.entries_skipped_no_starter} skipped, no starter)"
            )
            print(f"  {len(run_result.projections_published)} projections published")

            grade_result = grade_slate_run(session, SLATE_DATE, http_client=client)
            print(
                f"grade_slate_run: run_id={grade_result.run_id}, {len(grade_result.grades)} grades written"
            )

            games = games_for_slate_date(session, SLATE_DATE)
            current = current_projections_for_slate(session, [g.game_id for g in games])
            qualified = [p for p in current if p.decision_status == "QUALIFIED"]
            no_play = [p for p in current if p.decision == "NO_PLAY"]
            print(
                f"\nToday-page summary: {len(current)} evaluated, {len(qualified)} QUALIFIED, {len(no_play)} NO_PLAY"
            )

            print("\nGraded picks:")
            for p in qualified:
                grade = current_grade_for_projection(session, p.projection_id)
                result = grade.result if grade else "not graded yet"
                print(
                    f"  {p.player_id} line={p.line} {p.decision} ({p.decision_status}) -> {result}"
                )

            if args.dry_run:
                session.rollback()
                print("\n--dry-run: rolled back, nothing committed.")
            else:
                session.commit()
                print(
                    "\nCommitted. Run `cassandra grade 2023-06-15` again any time -- it's idempotent."
                )
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


if __name__ == "__main__":
    main()
