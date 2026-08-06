"""End-to-end integration test: real adapters (HTTP mocked against real
saved API responses), real ingestion, real Postgres, real snapshot build.

Cutoff semantics note: `ingested_at` is stamped at actual wall-clock
ingestion time, not the historical game date. So even though this test
replays a real 2023-06-15 game, the snapshot `cutoff_at` must be "now"
(when the test ingests), not a 2023 timestamp -- otherwise every row
would correctly (and unhelpfully, for this test) fail the as-of filter,
since we are, this instant, learning about a fact from the past. This is
exactly the semantics ADR 0001 requires: point-in-time is about when
*this system* learned something, not the calendar date of the fact.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import respx

from cassandra.adapters.lines_manual import LinesManualAdapter
from cassandra.adapters.lineups_mlb import LIVE_FEED_BASE, LineupMLBAdapter
from cassandra.adapters.park_factors_static import ParkFactorsStaticAdapter
from cassandra.adapters.pitcher_game_logs_mlb import PitcherGameLogsMLBAdapter
from cassandra.adapters.probable_pitchers_mlb import ProbablePitchersMLBAdapter
from cassandra.adapters.schedule_mlb import MLB_STATS_API_BASE, ScheduleMLBAdapter
from cassandra.adapters.weather_openmeteo import ARCHIVE_URL
from cassandra.ingestion.ingest_service import ingest
from cassandra.pit.snapshot_builder import build_snapshot

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "mlb_api"
SLATE_DATE = date(2023, 6, 15)
KIKUCHI_ID = 579328
KIKUCHI_GAME_PK = 717753
ORIOLES_TEAM_MLB_ID = 110  # home side of game 717753 -- who Kikuchi (Blue Jays) actually faces


def _lineup_feed_payload() -> dict:
    orioles_order = [640605, 641820, 592885, 592696, 664702, 543829, 606192, 656976, 519083]
    return {
        "gamePk": KIKUCHI_GAME_PK,
        "gameData": {"teams": {"home": {"id": ORIOLES_TEAM_MLB_ID}, "away": {"id": 141}}},
        "liveData": {
            "boxscore": {
                "teams": {
                    "home": {
                        "battingOrder": orioles_order,
                        "players": {
                            f"ID{pid}": {"person": {"id": pid}, "battingOrder": str(100 + i * 100)}
                            for i, pid in enumerate(orioles_order)
                        },
                    },
                    # Away (Blue Jays) lineup deliberately not posted yet
                    # -- irrelevant to Kikuchi's own entry, which only
                    # cares about the OPPONENT's (home/Orioles) lineup.
                    "away": {"battingOrder": [], "players": {}},
                }
            }
        },
    }


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@respx.mock
def _ingest_full_slate(session, tmp_path: Path) -> datetime:
    respx.get(f"{MLB_STATS_API_BASE}/schedule").mock(
        return_value=httpx.Response(200, json=_load("schedule_2023-06-15.json"))
    )
    respx.get(f"{MLB_STATS_API_BASE}/people/{KIKUCHI_ID}/stats").mock(
        return_value=httpx.Response(200, json=_load("gamelog_579328_2023.json"))
    )
    respx.get(ARCHIVE_URL).mock(return_value=httpx.Response(200, json=_load("weather_archive_camden.json")))
    respx.get(f"{LIVE_FEED_BASE}/game/{KIKUCHI_GAME_PK}/feed/live").mock(
        return_value=httpx.Response(200, json=_lineup_feed_payload())
    )

    ingest(session, ScheduleMLBAdapter(http_client=httpx.Client()), slate_date=SLATE_DATE)
    ingest(session, ProbablePitchersMLBAdapter(http_client=httpx.Client()), slate_date=SLATE_DATE)
    ingest(
        session,
        PitcherGameLogsMLBAdapter(http_client=httpx.Client()),
        slate_date=SLATE_DATE,
        player_mlb_ids=[KIKUCHI_ID],
    )
    ingest(
        session,
        LineupMLBAdapter(http_client=httpx.Client()),
        slate_date=SLATE_DATE,
        mlb_game_pks=[KIKUCHI_GAME_PK],
    )
    ingest(session, ParkFactorsStaticAdapter(), slate_date=SLATE_DATE, venue_ids=[2])

    from cassandra.adapters.weather_openmeteo import WeatherOpenMeteoAdapter

    ingest(
        session,
        WeatherOpenMeteoAdapter(http_client=httpx.Client()),
        slate_date=SLATE_DATE,
        venues=[
            {
                "venue_id": 2,
                "lat": 39.284,
                "lon": -76.6217,
                "game_time_utc": datetime(2023, 6, 15, 17, 5, tzinfo=UTC),
            }
        ],
    )

    lines_doc = {
        "slate_date": "2023-06-15",
        "observed_at": "2023-06-15T15:00:00Z",
        "lines": [
            {
                "mlb_game_pk": 717753,
                "player_mlb_id": KIKUCHI_ID,
                "market": "pitcher_strikeouts",
                "line": 5.5,
                "over_price": -115,
                "under_price": -105,
                "is_suspended": False,
            }
        ],
    }
    (tmp_path / "demo.json").write_text(json.dumps(lines_doc))
    ingest(session, LinesManualAdapter(drop_dir=tmp_path), slate_date=SLATE_DATE)

    session.flush()
    return datetime.now(UTC) + timedelta(minutes=1)


def test_full_ingest_then_snapshot_resolves_real_kikuchi_entry(db_session, tmp_path):
    cutoff = _ingest_full_slate(db_session, tmp_path)

    snapshot, entries = build_snapshot(db_session, SLATE_DATE, cutoff)
    db_session.flush()

    assert snapshot.status == "frozen"
    assert len(entries) >= 2  # both probable starters across the slate's games

    kikuchi_entries = [e for e in entries if e.probable and e.probable.player_mlb_id == KIKUCHI_ID]
    assert len(kikuchi_entries) == 1
    entry = kikuchi_entries[0]

    assert entry.probable is not None
    assert entry.probable.is_confirmed is True
    assert len(entry.game_logs) >= 1
    assert entry.park_factor is not None
    assert entry.park_factor.k_factor == 1.00
    assert entry.weather is not None
    assert len(entry.lines) == 1
    assert entry.lines[0].line == 5.5
    # Kikuchi pitches for the Blue Jays (away); the lineup that matters
    # for HIS entry is the Orioles' (home, the team he actually faces),
    # never his own team's -- see _lineup_feed_payload's deliberately
    # unposted away/Blue Jays lineup, proving this isn't just "whichever
    # side happened to be posted."
    assert entry.opponent_lineup is not None
    assert entry.opponent_lineup.team_mlb_id == ORIOLES_TEAM_MLB_ID

    reason_codes = {f.reason_code for f in entry.quality_findings}
    assert "DATA_MISSING" in reason_codes  # umpire, always
    assert "STARTER_UNCONFIRMED" not in reason_codes  # this pitcher demonstrably started
    assert "MARKET_CONTEXT_INCOMPLETE" not in reason_codes  # line was found
    assert "LINEUP_UNCONFIRMED" not in reason_codes  # opponent lineup was posted


def test_snapshot_raw_refs_recorded_for_included_rows(db_session, tmp_path):
    cutoff = _ingest_full_slate(db_session, tmp_path)
    snapshot, entries = build_snapshot(db_session, SLATE_DATE, cutoff)
    db_session.flush()

    from sqlalchemy import select

    from cassandra.db.models.snapshot import SnapshotRawRef

    refs = (
        db_session.execute(select(SnapshotRawRef).where(SnapshotRawRef.snapshot_id == snapshot.snapshot_id))
        .scalars()
        .all()
    )
    tables_referenced = {r.raw_table for r in refs}
    assert "raw_probable_pitchers" in tables_referenced
    assert "raw_pitcher_game_logs" in tables_referenced
    assert "raw_lines" in tables_referenced
    assert "raw_park_factors" in tables_referenced
    assert "raw_weather_observations" in tables_referenced
    assert "raw_lineups" in tables_referenced


def test_snapshot_missing_line_produces_market_context_incomplete(db_session, tmp_path):
    """Ingest everything except lines -- the snapshot must surface a
    MARKET_CONTEXT_INCOMPLETE finding rather than silently omitting it."""
    with respx.mock:
        respx.get(f"{MLB_STATS_API_BASE}/schedule").mock(
            return_value=httpx.Response(200, json=_load("schedule_2023-06-15.json"))
        )
        ingest(db_session, ScheduleMLBAdapter(http_client=httpx.Client()), slate_date=SLATE_DATE)
        ingest(
            db_session,
            ProbablePitchersMLBAdapter(http_client=httpx.Client()),
            slate_date=SLATE_DATE,
        )
    db_session.flush()
    cutoff = datetime.now(UTC) + timedelta(minutes=1)

    snapshot, entries = build_snapshot(db_session, SLATE_DATE, cutoff)
    kikuchi_entries = [e for e in entries if e.probable and e.probable.player_mlb_id == KIKUCHI_ID]
    assert len(kikuchi_entries) == 1
    entry = kikuchi_entries[0]
    reason_codes = {f.reason_code for f in entry.quality_findings}
    assert "MARKET_CONTEXT_INCOMPLETE" in reason_codes
    # No lineup was ingested at all in this test -- the opponent's lineup
    # is correctly unresolved, not silently defaulted to "confirmed".
    assert entry.opponent_lineup is None
    assert "LINEUP_UNCONFIRMED" in reason_codes
