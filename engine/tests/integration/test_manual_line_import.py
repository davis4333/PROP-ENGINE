"""ingestion/manual_line_import.py -- real Postgres, verifying matching
against real `raw_probable_pitchers`/`players` rows, ambiguous-name
handling, duplicate detection, and that commit only ever writes matched
entries as real `raw_lines` rows."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from cassandra.db.models.identity import Game, Player
from cassandra.db.models.raw import RawLine, RawProbablePitcher
from cassandra.db.models.sources import Source
from cassandra.ingestion.manual_line_import import (
    LineImportEntry,
    commit_line_import,
    preview_line_import,
)

SLATE_DATE = date(2023, 6, 15)
GAME_PK = 900030001
GAME_PK_2 = 900030002
PITCHER_A = 900031001  # "Test Pitcher A"
AMBIGUOUS_1 = 900031003  # "Same Name" (collides with AMBIGUOUS_2)
AMBIGUOUS_2 = 900031004  # "Same Name"


def _seed_game(session, mlb_game_pk: int) -> None:
    # 23:00 UTC on SLATE_DATE is a real evening-game start time that
    # still falls on SLATE_DATE in the operating timezone (US/Eastern,
    # UTC-4 in June) -- config.slate_date_for()'s conversion, not a raw
    # date match, is what actually decides slate membership (ADR 0009),
    # so a midnight-UTC timestamp would resolve to the *previous* day.
    session.add(
        Game(
            game_id=f"test-game-{mlb_game_pk}",
            mlb_game_pk=mlb_game_pk,
            game_date=datetime.combine(SLATE_DATE, datetime.min.time()),
            scheduled_start_utc=datetime.combine(SLATE_DATE, time(23, 0), tzinfo=UTC),
            status="Preview",
        )
    )


def _seed_probable(session, *, mlb_game_pk: int, player_mlb_id: int) -> None:
    session.add(
        RawProbablePitcher(
            source_id="test-source-manual-line-import",
            mlb_game_pk=mlb_game_pk,
            player_mlb_id=player_mlb_id,
            is_confirmed=True,
            observed_at=datetime.now(UTC),
            payload={},
        )
    )


def _seed_player(session, *, mlb_person_id: int, full_name: str) -> None:
    session.add(
        Player(player_id=f"test-player-{mlb_person_id}", mlb_person_id=mlb_person_id, full_name=full_name)
    )


def _seed_source(session) -> None:
    stmt = pg_insert(Source).values(
        source_id="test-source-manual-line-import", name="test-source-manual-line-import", kind="lines"
    )
    session.execute(stmt.on_conflict_do_nothing(index_elements=[Source.source_id]))


def _seed_base_slate(session) -> None:
    _seed_source(session)
    _seed_game(session, GAME_PK)
    _seed_probable(session, mlb_game_pk=GAME_PK, player_mlb_id=PITCHER_A)
    _seed_player(session, mlb_person_id=PITCHER_A, full_name="Test Pitcher A")
    session.flush()


def test_preview_matches_a_real_confirmed_starter_by_name(db_session):
    _seed_base_slate(db_session)

    preview = preview_line_import(
        db_session, SLATE_DATE, [LineImportEntry(player_name="Test Pitcher A", line=5.5, over_price=-110)]
    )

    assert len(preview.matched) == 1
    assert preview.matched[0].player_mlb_id == PITCHER_A
    assert preview.matched[0].mlb_game_pk == GAME_PK
    assert preview.matched[0].is_possible_duplicate is False
    assert preview.unmatched == []


def test_preview_reports_unmatched_name_with_a_clear_reason(db_session):
    _seed_base_slate(db_session)

    preview = preview_line_import(
        db_session, SLATE_DATE, [LineImportEntry(player_name="Nobody Pitching Today", line=5.5)]
    )

    assert preview.matched == []
    assert len(preview.unmatched) == 1
    assert "No confirmed starter" in preview.unmatched[0].reason


def test_preview_refuses_to_guess_on_an_ambiguous_name(db_session):
    _seed_source(db_session)
    _seed_game(db_session, GAME_PK)
    _seed_game(db_session, GAME_PK_2)
    _seed_probable(db_session, mlb_game_pk=GAME_PK, player_mlb_id=AMBIGUOUS_1)
    _seed_probable(db_session, mlb_game_pk=GAME_PK_2, player_mlb_id=AMBIGUOUS_2)
    _seed_player(db_session, mlb_person_id=AMBIGUOUS_1, full_name="Same Name")
    _seed_player(db_session, mlb_person_id=AMBIGUOUS_2, full_name="Same Name")
    db_session.flush()

    preview = preview_line_import(
        db_session, SLATE_DATE, [LineImportEntry(player_name="Same Name", line=5.5)]
    )

    assert preview.matched == []
    assert len(preview.unmatched) == 1
    assert "Ambiguous" in preview.unmatched[0].reason


def test_preview_flags_a_possible_duplicate_without_blocking_it(db_session):
    _seed_base_slate(db_session)
    db_session.add(
        RawLine(
            source_id="test-source-manual-line-import",
            mlb_game_pk=GAME_PK,
            player_mlb_id=PITCHER_A,
            market="pitcher_strikeouts",
            line=5.5,
            observed_at=datetime.now(UTC),
            payload={},
        )
    )
    db_session.flush()

    preview = preview_line_import(
        db_session, SLATE_DATE, [LineImportEntry(player_name="Test Pitcher A", line=6.5)]
    )

    assert len(preview.matched) == 1
    assert preview.matched[0].is_possible_duplicate is True


def test_commit_writes_only_matched_entries_as_real_raw_lines_rows(db_session):
    _seed_base_slate(db_session)
    entries = [
        LineImportEntry(player_name="Test Pitcher A", line=5.5, over_price=-115, under_price=-105),
        LineImportEntry(player_name="Nobody Pitching Today", line=4.5),
    ]

    result = commit_line_import(db_session, SLATE_DATE, entries)
    db_session.flush()

    assert result.records_written == 1
    assert len(result.warnings) == 1
    assert "Nobody Pitching Today" in result.warnings[0]

    rows = (
        db_session.execute(
            select(RawLine).where(RawLine.mlb_game_pk == GAME_PK, RawLine.player_mlb_id == PITCHER_A)
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert float(rows[0].line) == 5.5
    assert rows[0].payload["imported_via"] == "admin_manual_line_import"


def test_commit_is_append_only_and_never_overwrites_a_prior_import(db_session):
    _seed_base_slate(db_session)
    commit_line_import(db_session, SLATE_DATE, [LineImportEntry(player_name="Test Pitcher A", line=5.5)])
    commit_line_import(db_session, SLATE_DATE, [LineImportEntry(player_name="Test Pitcher A", line=6.5)])
    db_session.flush()

    rows = (
        db_session.execute(
            select(RawLine).where(RawLine.mlb_game_pk == GAME_PK, RawLine.player_mlb_id == PITCHER_A)
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert {float(r.line) for r in rows} == {5.5, 6.5}
