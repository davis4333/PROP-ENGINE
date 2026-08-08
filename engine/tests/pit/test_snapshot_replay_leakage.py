"""Adversarial point-in-time leakage tests at the snapshot/feature level
(ADR 0001). Where test_asof_primitive_leakage.py proves the as-of
primitives themselves refuse to leak, these prove the guarantee survives
through build_snapshot/build_features -- the actual path a real slate
takes -- including the specific claim in db/models/raw.py's module
docstring that `raw_final_box_scores` can never influence a projection.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError

from cassandra.db.models.identity import Game, Team
from cassandra.db.models.raw import RawFinalBoxScore, RawLineup, RawPitcherGameLog, RawProbablePitcher
from cassandra.db.models.sources import Source
from cassandra.features.builders import build_features
from cassandra.historical.challenger_poisson import COEFFICIENT_NAMES
from cassandra.pit.snapshot_builder import build_snapshot
from cassandra.registry.service import create_model_artifact, record_registry_event, resolve_active_model

# 900000000+ range, matching test_historical_backfill.py/test_dataset_builder.py's
# convention -- 110/111 were real MLB team IDs (Baltimore Orioles/Boston Red
# Sox), which collided with real seeded demo-slate data in a shared dev DB
# and broke every test in this file with a UniqueViolation on
# teams.mlb_team_id (found via this session's test-coverage audit).
GAME_PK = 999101
HOME_TEAM_MLB_ID = 900000110
AWAY_TEAM_MLB_ID = 900000111
SLATE_DATE = datetime(2024, 4, 1).date()
CUTOFF = datetime(2024, 4, 1, 22, 0, tzinfo=UTC)  # first pitch was 18:00 UTC
BEFORE = CUTOFF - timedelta(hours=2)
AFTER = CUTOFF + timedelta(hours=2)


def _make_source(session, source_id: str, kind: str = "pitcher_stats") -> None:
    stmt = pg_insert(Source).values(source_id=source_id, name=source_id, kind=kind)
    stmt = stmt.on_conflict_do_nothing(index_elements=[Source.source_id])
    session.execute(stmt)
    session.flush()


def _make_team(session, *, team_id: str, mlb_team_id: int) -> None:
    stmt = pg_insert(Team).values(team_id=team_id, mlb_team_id=mlb_team_id, name=team_id)
    stmt = stmt.on_conflict_do_nothing(index_elements=[Team.team_id])
    session.execute(stmt)
    session.flush()


def _make_game(session, *, game_id: str, mlb_game_pk: int) -> Game:
    _make_team(session, team_id="pit-home-team", mlb_team_id=HOME_TEAM_MLB_ID)
    stmt = pg_insert(Game).values(
        game_id=game_id,
        mlb_game_pk=mlb_game_pk,
        game_date=CUTOFF,
        scheduled_start_utc=CUTOFF - timedelta(hours=4),
        home_team_id="pit-home-team",
        away_team_id=None,
        venue_id=None,
        status="Final",
    )
    session.execute(stmt)
    session.flush()
    return session.get(Game, game_id)


def _make_game_two_teams(session, *, game_id: str, mlb_game_pk: int) -> Game:
    """Like _make_game, but with a real away team too -- needed to
    exercise opponent-lineup resolution, which requires two distinct
    teams in the game (_make_game's single-team games always resolve
    opponent_team_mlb_id to None, since there's no second team to be
    "the other one")."""
    _make_team(session, team_id="pit-home-team", mlb_team_id=HOME_TEAM_MLB_ID)
    _make_team(session, team_id="pit-away-team", mlb_team_id=AWAY_TEAM_MLB_ID)
    stmt = pg_insert(Game).values(
        game_id=game_id,
        mlb_game_pk=mlb_game_pk,
        game_date=CUTOFF,
        scheduled_start_utc=CUTOFF - timedelta(hours=4),
        home_team_id="pit-home-team",
        away_team_id="pit-away-team",
        venue_id=None,
        status="Final",
    )
    session.execute(stmt)
    session.flush()
    return session.get(Game, game_id)


def _lineup(
    session,
    *,
    source_id: str,
    mlb_game_pk: int,
    team_mlb_id: int,
    observed_at: datetime,
    ingested_at: datetime,
) -> RawLineup:
    row = RawLineup(
        raw_id=uuid.uuid4(),
        source_id=source_id,
        mlb_game_pk=mlb_game_pk,
        team_mlb_id=team_mlb_id,
        batting_order={"order": [], "slots": {}},
        is_confirmed=True,
        observed_at=observed_at,
        ingested_at=ingested_at,
        payload={},
    )
    session.add(row)
    session.flush()
    return row


def _probable(
    session, *, source_id, mlb_game_pk, player_mlb_id, team_mlb_id, observed_at, ingested_at
) -> None:
    session.add(
        RawProbablePitcher(
            raw_id=uuid.uuid4(),
            source_id=source_id,
            mlb_game_pk=mlb_game_pk,
            player_mlb_id=player_mlb_id,
            team_mlb_id=team_mlb_id,
            is_confirmed=True,
            observed_at=observed_at,
            ingested_at=ingested_at,
            payload={},
        )
    )
    session.flush()


def test_late_arriving_starter_swap_invisible_to_a_snapshot_frozen_before_it(db_session):
    """A pitcher gets scratched and replaced after the original snapshot's
    cutoff. Rebuilding at the SAME cutoff must still show the original
    starter -- the frozen point in time never moves just because more
    data arrived."""
    _make_source(db_session, "src-swap")
    _make_game(db_session, game_id="pit-game-swap", mlb_game_pk=GAME_PK)

    _probable(
        db_session,
        source_id="src-swap",
        mlb_game_pk=GAME_PK,
        player_mlb_id=5001,
        team_mlb_id=HOME_TEAM_MLB_ID,
        observed_at=BEFORE,
        ingested_at=BEFORE,
    )

    snapshot, entries = build_snapshot(db_session, SLATE_DATE, CUTOFF)
    entry = next(e for e in entries if e.team_mlb_id == HOME_TEAM_MLB_ID)
    assert entry.probable is not None
    assert entry.probable.player_mlb_id == 5001

    # The scratch/replacement arrives -- physically written after the
    # original cutoff.
    _probable(
        db_session,
        source_id="src-swap",
        mlb_game_pk=GAME_PK,
        player_mlb_id=5002,
        team_mlb_id=HOME_TEAM_MLB_ID,
        observed_at=AFTER,
        ingested_at=AFTER,
    )

    # Rebuilding at the SAME cutoff (as a replay/backtest would) must
    # reproduce the exact same frozen view -- never the replacement.
    _, entries_replayed = build_snapshot(db_session, SLATE_DATE, CUTOFF)
    entry_replayed = next(e for e in entries_replayed if e.team_mlb_id == HOME_TEAM_MLB_ID)
    assert entry_replayed.probable is not None
    assert entry_replayed.probable.player_mlb_id == 5001, (
        "replaying the same cutoff must never pick up data ingested after it"
    )


def test_late_arriving_lineup_swap_invisible_to_a_snapshot_frozen_before_it(db_session):
    """The lineup analogue of the starter-swap test above: the opponent's
    batting order changes (a late scratch/reshuffle) after the original
    snapshot's cutoff. Rebuilding at the SAME cutoff must still show the
    original lineup version -- not the swap, no matter how much more
    "correct" or "current" it is in real time."""
    _make_source(db_session, "src-lineup-swap")
    _make_game_two_teams(db_session, game_id="pit-game-lineup-swap", mlb_game_pk=GAME_PK + 3)

    # The home team's pitcher -- opponent_lineup on his entry should
    # resolve to the AWAY team's lineup (who he actually faces).
    _probable(
        db_session,
        source_id="src-lineup-swap",
        mlb_game_pk=GAME_PK + 3,
        player_mlb_id=8001,
        team_mlb_id=HOME_TEAM_MLB_ID,
        observed_at=BEFORE,
        ingested_at=BEFORE,
    )
    original_lineup = _lineup(
        db_session,
        source_id="src-lineup-swap",
        mlb_game_pk=GAME_PK + 3,
        team_mlb_id=AWAY_TEAM_MLB_ID,
        observed_at=BEFORE,
        ingested_at=BEFORE,
    )

    snapshot, entries = build_snapshot(db_session, SLATE_DATE, CUTOFF)
    entry = next(e for e in entries if e.team_mlb_id == HOME_TEAM_MLB_ID)
    assert entry.opponent_lineup is not None
    assert entry.opponent_lineup.raw_id == original_lineup.raw_id

    # A late reshuffle/replacement lineup arrives -- physically written
    # after the original cutoff.
    _lineup(
        db_session,
        source_id="src-lineup-swap",
        mlb_game_pk=GAME_PK + 3,
        team_mlb_id=AWAY_TEAM_MLB_ID,
        observed_at=AFTER,
        ingested_at=AFTER,
    )

    # Rebuilding at the SAME cutoff (as a replay/backtest would) must
    # reproduce the exact same frozen opponent lineup -- never the swap.
    _, entries_replayed = build_snapshot(db_session, SLATE_DATE, CUTOFF)
    entry_replayed = next(e for e in entries_replayed if e.team_mlb_id == HOME_TEAM_MLB_ID)
    assert entry_replayed.opponent_lineup is not None
    assert entry_replayed.opponent_lineup.raw_id == original_lineup.raw_id, (
        "replaying the same cutoff must never pick up a lineup ingested after it"
    )


def test_rerun_at_same_cutoff_creates_a_new_snapshot_never_mutates_the_first(db_session):
    _make_source(db_session, "src-rerun")
    _make_game(db_session, game_id="pit-game-rerun", mlb_game_pk=GAME_PK + 1)
    _probable(
        db_session,
        source_id="src-rerun",
        mlb_game_pk=GAME_PK + 1,
        player_mlb_id=6001,
        team_mlb_id=HOME_TEAM_MLB_ID,
        observed_at=BEFORE,
        ingested_at=BEFORE,
    )
    first, _ = build_snapshot(db_session, SLATE_DATE, CUTOFF)
    second, _ = build_snapshot(db_session, SLATE_DATE, CUTOFF)

    assert first.snapshot_id != second.snapshot_id
    assert first.status == "frozen"
    assert second.status == "frozen"


def test_frozen_snapshot_update_is_blocked_by_the_immutability_trigger(db_session):
    _make_source(db_session, "src-snap-immut-update")
    _make_game(db_session, game_id="pit-game-snap-immut-update", mlb_game_pk=GAME_PK + 2)
    snapshot, _ = build_snapshot(db_session, SLATE_DATE, CUTOFF)
    db_session.flush()
    with pytest.raises(DBAPIError, match="append-only"):
        db_session.execute(
            text("UPDATE snapshots SET notes = 'hacked' WHERE snapshot_id = :id"),
            {"id": snapshot.snapshot_id},
        )


def test_frozen_snapshot_delete_is_blocked(db_session):
    _make_source(db_session, "src-snap-immut-delete")
    _make_game(db_session, game_id="pit-game-snap-immut-delete", mlb_game_pk=GAME_PK + 3)
    snapshot, _ = build_snapshot(db_session, SLATE_DATE, CUTOFF)
    db_session.flush()
    with pytest.raises(DBAPIError):
        db_session.execute(
            text("DELETE FROM snapshots WHERE snapshot_id = :id"),
            {"id": snapshot.snapshot_id},
        )


def test_snapshot_raw_refs_update_is_blocked(db_session):
    _make_source(db_session, "src-snap-refs-immut")
    _make_game(db_session, game_id="pit-game-snap-refs-immut", mlb_game_pk=GAME_PK + 4)
    _probable(
        db_session,
        source_id="src-snap-refs-immut",
        mlb_game_pk=GAME_PK + 4,
        player_mlb_id=6002,
        team_mlb_id=HOME_TEAM_MLB_ID,
        observed_at=BEFORE,
        ingested_at=BEFORE,
    )
    snapshot, _ = build_snapshot(db_session, SLATE_DATE, CUTOFF)
    db_session.flush()
    ref = db_session.execute(
        text("SELECT snapshot_id, raw_table, raw_id FROM snapshot_raw_refs WHERE snapshot_id = :id LIMIT 1"),
        {"id": snapshot.snapshot_id},
    ).first()
    assert ref is not None, "expected at least one snapshot_raw_refs row for this snapshot"
    with pytest.raises(DBAPIError, match="append-only"):
        db_session.execute(
            text(
                "UPDATE snapshot_raw_refs SET natural_key = 'hacked' "
                "WHERE snapshot_id = :sid AND raw_table = :rt AND raw_id = :rid"
            ),
            {"sid": ref.snapshot_id, "rt": ref.raw_table, "rid": ref.raw_id},
        )


def test_snapshot_data_quality_update_is_blocked(db_session):
    _make_source(db_session, "src-snap-dq-immut")
    _make_game(db_session, game_id="pit-game-snap-dq-immut", mlb_game_pk=GAME_PK + 5)
    snapshot, _ = build_snapshot(db_session, SLATE_DATE, CUTOFF)
    db_session.flush()
    dq_id = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO snapshot_data_quality (id, snapshot_id, check_name, status) "
            "VALUES (:id, :sid, 'test_check', 'warn')"
        ),
        {"id": dq_id, "sid": snapshot.snapshot_id},
    )
    db_session.flush()
    with pytest.raises(DBAPIError, match="append-only"):
        db_session.execute(
            text("UPDATE snapshot_data_quality SET detail = 'hacked' WHERE id = :id"),
            {"id": dq_id},
        )


def test_final_box_score_value_never_appears_in_computed_features(db_session):
    """Seed a Final box score for the exact player/game being projected,
    with a deliberately extreme, unmistakable value. If it ever leaked
    into feature computation, it would completely dominate expected_bf/
    recent_k_rate. Assert it does not appear anywhere in the output."""
    _make_source(db_session, "src-boxleak", kind="pitcher_stats")
    _make_game(db_session, game_id="pit-game-boxleak", mlb_game_pk=GAME_PK + 2)
    player_mlb_id = 7001
    _probable(
        db_session,
        source_id="src-boxleak",
        mlb_game_pk=GAME_PK + 2,
        player_mlb_id=player_mlb_id,
        team_mlb_id=HOME_TEAM_MLB_ID,
        observed_at=BEFORE,
        ingested_at=BEFORE,
    )

    sentinel = 999999
    db_session.add(
        RawFinalBoxScore(
            raw_id=uuid.uuid4(),
            source_id="src-boxleak",
            mlb_game_pk=GAME_PK + 2,
            player_mlb_id=player_mlb_id,
            strikeouts_recorded=sentinel,
            innings_pitched=6.0,
            pitch_count=95,
            game_status="Final",
            observed_at=BEFORE,
            ingested_at=BEFORE,
            payload={"strikeouts": sentinel},
        )
    )
    db_session.flush()

    _, entries = build_snapshot(db_session, SLATE_DATE, CUTOFF)
    entry = next(e for e in entries if e.team_mlb_id == HOME_TEAM_MLB_ID)
    features = build_features(entry, CUTOFF)

    assert sentinel not in features.values()
    assert str(sentinel) not in str(features), "the sentinel box-score value leaked into computed features"


def _game_log(
    session, *, source_id, player_mlb_id, stat_date, strikeouts, batters_faced, observed_at, ingested_at
) -> None:
    session.add(
        RawPitcherGameLog(
            raw_id=uuid.uuid4(),
            source_id=source_id,
            player_mlb_id=player_mlb_id,
            mlb_game_pk=None,
            stat_date=stat_date,
            batters_faced=batters_faced,
            strikeouts=strikeouts,
            pitch_count=90,
            innings_pitched=6.0,
            observed_at=observed_at,
            ingested_at=ingested_at,
            payload={},
        )
    )
    session.flush()


def test_late_arriving_game_log_invisible_to_a_promoted_non_baseline_model(db_session):
    """Regression for a gap an independent leakage audit found: every PIT
    test up to this point only ever exercised the permanent baseline
    model. registry/service.py's resolve_active_model() can now return a
    promoted poisson-regression challenger instead (2026-08-08's real
    promotion) -- this proves the shared pit/asof.py cutoff gate still
    holds for that path too, not just for run_slate.py's default
    configuration. A late-arriving game log with a deliberately extreme
    strikeout total is added *after* the original cutoff; replaying at
    the SAME cutoff, with a promoted challenger ACTIVE, must produce the
    exact same prediction both times."""
    _make_source(db_session, "src-modelswap")
    _make_game(db_session, game_id="pit-game-modelswap", mlb_game_pk=GAME_PK + 3)
    player_mlb_id = 7002
    _probable(
        db_session,
        source_id="src-modelswap",
        mlb_game_pk=GAME_PK + 3,
        player_mlb_id=player_mlb_id,
        team_mlb_id=HOME_TEAM_MLB_ID,
        observed_at=BEFORE,
        ingested_at=BEFORE,
    )
    _game_log(
        db_session,
        source_id="src-modelswap",
        player_mlb_id=player_mlb_id,
        stat_date=BEFORE,
        strikeouts=6,
        batters_faced=24,
        observed_at=BEFORE,
        ingested_at=BEFORE,
    )

    artifact = create_model_artifact(
        db_session,
        model_family="poisson-regression",
        model_code_version="poisson-regression-challenger-0.1.0",
        coefficients=[0.5, 0.1, 2.0, -0.02, 0.0],
        coefficient_order=list(COEFFICIENT_NAMES),
        preprocessing_rules={},
        training_dataset_id="ds_pit_test",
        dataset_builder_version="v1",
        availability_policy_version="v1",
        feature_set_version="v1",
        training_seasons=[2023],
        training_game_types=["R"],
        training_row_count=500,
        trained_at=CUTOFF,
        dependency_versions={},
        training_metrics={},
        evaluation_report_ids=[],
        created_by="pit-test",
    )
    record_registry_event(
        db_session,
        artifact_id=artifact.artifact_id,
        event_type="activated",
        to_status="ACTIVE",
        operator="pit-test",
        from_status="CANDIDATE",
    )
    resolved = resolve_active_model(db_session)
    assert resolved.active_artifact_id == artifact.artifact_id  # promotion actually took

    _, entries = build_snapshot(db_session, SLATE_DATE, CUTOFF)
    entry = next(e for e in entries if e.team_mlb_id == HOME_TEAM_MLB_ID)
    features_before = build_features(entry, CUTOFF)
    prediction_before = resolved.model.predict(features_before).mean

    # A wildly extreme late-arriving start -- physically written after
    # the original cutoff. If the leakage gate were ever bypassed on the
    # promoted-model path, this would visibly blow up recent_k_rate/
    # expected_bf and shift the prediction.
    _game_log(
        db_session,
        source_id="src-modelswap",
        player_mlb_id=player_mlb_id,
        stat_date=AFTER,
        strikeouts=19,
        batters_faced=27,
        observed_at=AFTER,
        ingested_at=AFTER,
    )

    _, entries_replayed = build_snapshot(db_session, SLATE_DATE, CUTOFF)
    entry_replayed = next(e for e in entries_replayed if e.team_mlb_id == HOME_TEAM_MLB_ID)
    features_replayed = build_features(entry_replayed, CUTOFF)
    prediction_replayed = resolved.model.predict(features_replayed).mean

    assert features_replayed == features_before, "replaying the same cutoff must reproduce identical features"
    assert prediction_replayed == prediction_before, (
        "a promoted non-baseline model must never see a late-arriving stat line "
        "just because more data has since arrived"
    )
