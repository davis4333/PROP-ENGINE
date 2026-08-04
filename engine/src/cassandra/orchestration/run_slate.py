"""Ties the whole pipeline together for one slate: INGEST -> VALIDATE ->
FREEZE -> PROJECT -> REVIEW -> PUBLISH (`run_slate`), and separately GRADE
(`grade_slate_run`, called once games are Final -- typically hours after
`run_slate`, so it's a distinct entry point with its own `pipeline_runs`
row rather than a trailing stage of the same call).

Every stage's start/success/failure is written to `pipeline_run_stages`
(ADR 0007's authority for later admin action guards) -- this is what
drives the Admin page's pipeline tracker. VALIDATE has no separate code
path: the data-quality checks it names actually run inside FREEZE's
`pit.snapshot_builder.build_snapshot` (their output is what
`snapshot_data_quality` rows already are), so VALIDATE is marked
succeeded alongside FREEZE with a detail note explaining that, rather
than pretending a second pass happens.

Rerunning `run_slate` for the same slate never mutates anything --
ingestion appends new raw rows, `build_snapshot` always creates a new
`Snapshot`, and `ledger.publish_projection` always creates a new
projection version. Every call is a new `PipelineRun` row.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from cassandra.adapters.final_box_scores_mlb import FinalBoxScoresMLBAdapter
from cassandra.adapters.lines_manual import LinesManualAdapter
from cassandra.adapters.park_factors_static import ParkFactorsStaticAdapter
from cassandra.adapters.pitcher_game_logs_mlb import PitcherGameLogsMLBAdapter
from cassandra.adapters.probable_pitchers_mlb import ProbablePitchersMLBAdapter
from cassandra.adapters.schedule_mlb import ScheduleMLBAdapter
from cassandra.adapters.umpire_stub import UmpireStubAdapter
from cassandra.adapters.weather_openmeteo import WeatherOpenMeteoAdapter
from cassandra.db.models.audit import AuditEvent
from cassandra.db.models.features import FeatureSet, FeatureValue
from cassandra.db.models.grading import Grade
from cassandra.db.models.identity import Game, Venue
from cassandra.db.models.pipeline import PipelineRun, PipelineRunStage
from cassandra.db.models.projection import Projection
from cassandra.db.models.raw import RawProbablePitcher
from cassandra.decision.engine import Decision, decide
from cassandra.features.builders import FEATURE_SET_VERSION, build_features
from cassandra.grading.service import grade_slate
from cassandra.identity_ids import mlb_player_id
from cassandra.ingestion.ingest_service import IngestResult, ingest
from cassandra.ledger.service import current_projections_for_slate, publish_projection
from cassandra.models.baseline import MODEL_VERSION, BaselinePoissonModel
from cassandra.pit.asof import all_as_of
from cassandra.pit.snapshot_builder import PitcherSlateEntry, build_snapshot, games_for_slate_date

# Known venue coordinates for the (free) Open-Meteo weather adapter -- MLB's
# own schedule/venue payload doesn't include lat/lon, and there's no
# identity.py column for it (see db/models/identity.py's Venue model).
# Same provisional-static-lookup pattern as
# adapters/park_factors_static.py's STATIC_PARK_K_FACTORS: legitimate for
# an MVP, not a claim of complete coverage -- an unlisted venue simply
# gets no weather record (a visible gap via WeatherOpenMeteoAdapter's
# normal "no venues supplied"-style warning), never a guess.
VENUE_COORDINATES: dict[int, tuple[float, float]] = {
    2: (39.284, -76.6217),  # Oriole Park at Camden Yards -- the fixture demo slate's venue
}


@dataclass
class RunSlateResult:
    run_id: str
    slate_date: date
    cutoff_at: datetime
    snapshot_id: uuid.UUID | None = None
    ingest_results: list[IngestResult] = field(default_factory=list)
    entries_frozen: int = 0
    entries_skipped_no_starter: int = 0
    projections_published: list[Projection] = field(default_factory=list)


@dataclass
class GradeSlateResult:
    run_id: str
    slate_date: date
    grades: list[Grade] = field(default_factory=list)


def _new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:20]}"


def _start_run(session: Session, run_id: str, slate_date: date) -> None:
    session.add(PipelineRun(run_id=run_id, slate_date=slate_date, status="running", current_stage="INGEST"))
    session.flush()


def _stage(
    session: Session,
    run_id: str,
    stage: str,
    status: str,
    detail: str | None = None,
    *,
    started: bool = False,
) -> None:
    """Upsert one `pipeline_run_stages` row -- called once to mark a stage
    `running` and again to mark it `succeeded`/`failed`/`skipped`."""
    now = datetime.now(UTC)
    values: dict[str, Any] = {"run_id": run_id, "stage": stage, "status": status, "detail": detail}
    update_cols: dict[str, Any] = {"status": status, "detail": detail}
    if started:
        values["started_at"] = now
        update_cols["started_at"] = now
    else:
        values["finished_at"] = now
        update_cols["finished_at"] = now
    stmt = pg_insert(PipelineRunStage).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[PipelineRunStage.run_id, PipelineRunStage.stage], set_=update_cols
    )
    session.execute(stmt)

    run = session.get(PipelineRun, run_id)
    if run is not None:
        run.current_stage = stage


def _finish_run(session: Session, run_id: str, *, status: str) -> None:
    run = session.get(PipelineRun, run_id)
    if run is not None:
        run.status = status


def _ensure_feature_set(session: Session, version: str) -> None:
    stmt = pg_insert(FeatureSet).values(
        feature_set_version=version, description="Baseline model feature set -- see features/registry.py"
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=[FeatureSet.feature_set_version])
    session.execute(stmt)


def run_slate(
    session: Session,
    slate_date: date,
    cutoff_at: datetime,
    *,
    http_client: httpx.Client | None = None,
    lines_drop_dir: Path | None = None,
    edge_threshold: float | None = None,
    publish: bool = True,
) -> RunSlateResult:
    if cutoff_at.tzinfo is None:
        raise ValueError("cutoff_at must be timezone-aware (UTC)")

    run_id = _new_run_id()
    client = http_client or httpx.Client(timeout=10.0)
    result = RunSlateResult(run_id=run_id, slate_date=slate_date, cutoff_at=cutoff_at)
    _start_run(session, run_id, slate_date)

    try:
        _stage(session, run_id, "INGEST", "running", started=True)
        result.ingest_results = _ingest_slate(
            session, slate_date, cutoff_at, client, lines_drop_dir=lines_drop_dir, run_id=run_id
        )
        session.flush()
        failed_sources = [r.source_name for r in result.ingest_results if not r.is_available]
        _stage(
            session,
            run_id,
            "INGEST",
            "succeeded",
            detail=f"{len(result.ingest_results)} sources attempted; unavailable: {failed_sources or 'none'}",
        )

        _stage(session, run_id, "VALIDATE", "running", started=True)
        _stage(
            session,
            run_id,
            "VALIDATE",
            "succeeded",
            detail=(
                "Data-quality checks run inside FREEZE's build_snapshot; "
                "see this run's snapshot_data_quality rows."
            ),
        )

        _stage(session, run_id, "FREEZE", "running", started=True)
        snapshot, entries = build_snapshot(session, slate_date, cutoff_at)
        session.flush()
        result.snapshot_id = snapshot.snapshot_id
        result.entries_frozen = len(entries)
        _stage(session, run_id, "FREEZE", "succeeded", detail=f"{len(entries)} pitcher-slate entries frozen")

        _stage(session, run_id, "PROJECT", "running", started=True)
        _ensure_feature_set(session, FEATURE_SET_VERSION)
        projectable: list[PitcherSlateEntry] = [e for e in entries if e.probable is not None]
        result.entries_skipped_no_starter = len(entries) - len(projectable)
        model = BaselinePoissonModel()
        features_by_entry: dict[int, dict[str, Any]] = {
            i: build_features(e, cutoff_at) for i, e in enumerate(projectable)
        }
        session.flush()
        _stage(
            session,
            run_id,
            "PROJECT",
            "succeeded",
            detail=(
                f"{len(projectable)} entries projected; "
                f"{result.entries_skipped_no_starter} skipped (no confirmed starter, DATA_MISSING)"
            ),
        )

        _stage(session, run_id, "REVIEW", "running", started=True)
        decisions_by_entry: dict[int, tuple[float | None, Decision]] = {}
        for i, entry in enumerate(projectable):
            dist = model.predict(features_by_entry[i])
            raw_line = float(entry.lines[0].line) if entry.lines else None
            decide_line = raw_line if raw_line is not None else 0.5
            decisions_by_entry[i] = (
                raw_line,
                decide(decide_line, dist, entry.quality_findings, edge_threshold=edge_threshold),
            )
        qualified = sum(1 for _, d in decisions_by_entry.values() if d.decision_status == "QUALIFIED")
        _stage(
            session,
            run_id,
            "REVIEW",
            "succeeded",
            detail=f"{len(decisions_by_entry)} decisions made; {qualified} QUALIFIED",
        )

        _stage(session, run_id, "PUBLISH", "running", started=True)
        for i, entry in enumerate(projectable):
            raw_line, decision = decisions_by_entry[i]
            assert entry.probable is not None  # guaranteed by the `projectable` filter above
            player_id = mlb_player_id(entry.probable.player_mlb_id)
            session.add(
                FeatureValue(
                    snapshot_id=snapshot.snapshot_id,
                    player_id=player_id,
                    game_id=entry.game.game_id,
                    feature_set_version=FEATURE_SET_VERSION,
                    features=features_by_entry[i],
                )
            )
            row = publish_projection(
                session,
                run_id=run_id,
                snapshot=snapshot,
                game=entry.game,
                player_id=player_id,
                line=raw_line,
                feature_set_version=FEATURE_SET_VERSION,
                features=features_by_entry[i],
                model_version=MODEL_VERSION,
                decision=decision,
                as_of=cutoff_at,
                publish=publish,
            )
            result.projections_published.append(row)
        session.flush()
        _stage(
            session,
            run_id,
            "PUBLISH",
            "succeeded",
            detail=f"{len(result.projections_published)} projection rows written (publish={publish})",
        )

        _stage(session, run_id, "GRADE", "skipped", detail="Grading happens separately via grade_slate_run")
        _finish_run(session, run_id, status="succeeded")
    except Exception as exc:
        _finish_run(session, run_id, status="failed")
        session.add(
            AuditEvent(
                event_type="RUN_FAILED",
                entity_type="pipeline_run",
                entity_id=run_id,
                run_id=run_id,
                payload={"error": str(exc)},
            )
        )
        raise

    return result


def _ingest_slate(
    session: Session,
    slate_date: date,
    cutoff_at: datetime,
    client: httpx.Client,
    *,
    lines_drop_dir: Path | None,
    run_id: str,
) -> list[IngestResult]:
    results: list[IngestResult] = []

    results.append(
        ingest(
            session,
            ScheduleMLBAdapter(http_client=client),
            slate_date=slate_date,
            as_of=cutoff_at,
            run_id=run_id,
        )
    )
    session.flush()

    results.append(
        ingest(
            session,
            ProbablePitchersMLBAdapter(http_client=client),
            slate_date=slate_date,
            as_of=cutoff_at,
            run_id=run_id,
        )
    )
    session.flush()

    games = games_for_slate_date(session, slate_date)
    probables: list[RawProbablePitcher] = []
    for game in games:
        probables.extend(all_as_of(session, RawProbablePitcher, {"mlb_game_pk": game.mlb_game_pk}, cutoff_at))
    player_mlb_ids = sorted({p.player_mlb_id for p in probables})

    results.append(
        ingest(
            session,
            PitcherGameLogsMLBAdapter(http_client=client),
            slate_date=slate_date,
            as_of=cutoff_at,
            run_id=run_id,
            player_mlb_ids=player_mlb_ids,
        )
    )

    venues = _venues_for_games(session, games)
    venue_ids = sorted({v.mlb_venue_id for v in venues if v.mlb_venue_id is not None})
    results.append(
        ingest(
            session,
            ParkFactorsStaticAdapter(),
            slate_date=slate_date,
            as_of=cutoff_at,
            run_id=run_id,
            venue_ids=venue_ids,
        )
    )

    weather_venues = [
        {
            "venue_id": vid,
            "lat": VENUE_COORDINATES[vid][0],
            "lon": VENUE_COORDINATES[vid][1],
            "game_time_utc": cutoff_at,
        }
        for vid in venue_ids
        if vid in VENUE_COORDINATES
    ]
    results.append(
        ingest(
            session,
            WeatherOpenMeteoAdapter(http_client=client),
            slate_date=slate_date,
            as_of=cutoff_at,
            run_id=run_id,
            venues=weather_venues,
        )
    )

    results.append(
        ingest(session, UmpireStubAdapter(), slate_date=slate_date, as_of=cutoff_at, run_id=run_id)
    )

    results.append(
        ingest(
            session,
            LinesManualAdapter(drop_dir=lines_drop_dir),
            slate_date=slate_date,
            as_of=cutoff_at,
            run_id=run_id,
        )
    )

    return results


def _venues_for_games(session: Session, games: list[Game]) -> list[Venue]:
    venue_ids = {g.venue_id for g in games if g.venue_id is not None}
    if not venue_ids:
        return []
    return list(session.execute(select(Venue).where(Venue.venue_id.in_(venue_ids))).scalars().all())


def grade_slate_run(
    session: Session,
    slate_date: date,
    *,
    http_client: httpx.Client | None = None,
) -> GradeSlateResult:
    """Ingests the current box scores for every game in the slate, then
    grades every current (latest-version), published projection whose
    game now has a Final box score. Safe to call repeatedly -- ungradeable
    projections (game not Final yet) are silently skipped (ADR 0007), and
    grading itself is idempotent when nothing changed (see
    grading.service.grade_projection)."""
    run_id = _new_run_id()
    client = http_client or httpx.Client(timeout=10.0)
    _start_run(session, run_id, slate_date)

    for stage in ("INGEST", "VALIDATE", "FREEZE", "PROJECT", "REVIEW", "PUBLISH"):
        _stage(session, run_id, stage, "skipped", detail="Not part of grade_slate_run")

    graded: list[Grade] = []
    try:
        _stage(session, run_id, "GRADE", "running", started=True)

        games = games_for_slate_date(session, slate_date)
        game_pks = [g.mlb_game_pk for g in games if g.mlb_game_pk is not None]
        ingest_result = ingest(
            session,
            FinalBoxScoresMLBAdapter(http_client=client),
            slate_date=slate_date,
            run_id=run_id,
            mlb_game_pks=game_pks,
        )
        session.flush()

        game_ids = [g.game_id for g in games]
        current = current_projections_for_slate(session, game_ids)
        graded = grade_slate(session, current, run_id)
        session.flush()

        _stage(
            session,
            run_id,
            "GRADE",
            "succeeded",
            detail=(
                f"box scores available={ingest_result.is_available}; "
                f"{len(current)} current projections considered; {len(graded)} graded"
            ),
        )
        _finish_run(session, run_id, status="succeeded")
    except Exception as exc:
        _finish_run(session, run_id, status="failed")
        session.add(
            AuditEvent(
                event_type="RUN_FAILED",
                entity_type="pipeline_run",
                entity_id=run_id,
                run_id=run_id,
                payload={"error": str(exc)},
            )
        )
        raise

    return GradeSlateResult(run_id=run_id, slate_date=slate_date, grades=graded)
