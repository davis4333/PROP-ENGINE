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
from cassandra.adapters.lines_odds_api import LinesOddsApiAdapter
from cassandra.adapters.park_factors_static import ParkFactorsStaticAdapter
from cassandra.adapters.pitcher_game_logs_mlb import PitcherGameLogsMLBAdapter
from cassandra.adapters.probable_pitchers_mlb import ProbablePitchersMLBAdapter
from cassandra.adapters.schedule_mlb import ScheduleMLBAdapter
from cassandra.adapters.umpire_stub import UmpireStubAdapter
from cassandra.adapters.weather_openmeteo import WeatherOpenMeteoAdapter
from cassandra.config import operating_tz, settings
from cassandra.db.models.audit import AuditEvent
from cassandra.db.models.features import FeatureSet, FeatureValue
from cassandra.db.models.grading import Grade
from cassandra.db.models.identity import Game, Player, Venue
from cassandra.db.models.pipeline import PipelineRun, PipelineRunStage
from cassandra.db.models.projection import Projection
from cassandra.db.models.raw import RawProbablePitcher
from cassandra.db.models.sources import SourceHealth
from cassandra.decision.engine import Decision, decide
from cassandra.features.builders import FEATURE_SET_VERSION, build_features
from cassandra.grading.service import grade_slate
from cassandra.identity_ids import mlb_player_id
from cassandra.ingestion.ingest_service import IngestResult, ingest
from cassandra.ledger.service import current_projections_for_slate, publish_projection
from cassandra.models.baseline import MODEL_VERSION, BaselinePoissonModel
from cassandra.pit.asof import all_as_of
from cassandra.pit.snapshot_builder import PitcherSlateEntry, build_snapshot, games_for_slate_date

# Venue coordinates for the (free) Open-Meteo weather adapter -- MLB's own
# schedule/venue payload doesn't include lat/lon, and there's no
# identity.py column for it (see db/models/identity.py's Venue model).
# All 30 current active-team home venues, pulled directly from MLB's own
# Stats API (GET /api/v1/venues?venueIds=...&hydrate=location -- the same
# free, public, no-key source every other adapter in this codebase already
# uses, not a third-party guess) rather than typed from memory, since MLB
# venue ids are internal and teams do relocate (e.g. the Athletics moved to
# Sutter Health Park in Sacramento, venue id 2529, mid-build). Regenerate by
# re-running that same query if a team relocates or a new park opens --
# this is deliberately a static table, not a live lookup, so an unlisted
# venue (a spring-training park, a one-off international/neutral-site game)
# simply gets no weather record: a visible gap via
# WeatherOpenMeteoAdapter's normal "no venues supplied"-style warning, never
# a guess. Same provisional-static-lookup pattern as
# adapters/park_factors_static.py's STATIC_PARK_K_FACTORS.
#
# Known remaining gap, documented not silent: domes/retractable-roof parks
# (Tropicana Field, Rogers Centre, Chase Field, American Family Field,
# T-Mobile Park, Daikin Park, loanDepot park, Globe Life Field) still get an
# outdoor weather forecast fetched -- there's no per-game roof-open/closed
# signal available from this data source, so wind/temperature features may
# not reflect actual in-game conditions at those venues.
VENUE_COORDINATES: dict[int, tuple[float, float]] = {
    1: (33.80019044, -117.8823996),  # Angel Stadium -- Los Angeles Angels
    2: (39.283787, -76.621689),  # Oriole Park at Camden Yards -- Baltimore Orioles
    3: (42.346456, -71.097441),  # Fenway Park -- Boston Red Sox
    4: (41.83, -87.634167),  # Rate Field -- Chicago White Sox
    5: (41.495861, -81.685255),  # Progressive Field -- Cleveland Guardians
    7: (39.051567, -94.480483),  # Kauffman Stadium -- Kansas City Royals
    12: (27.767778, -82.6525),  # Tropicana Field -- Tampa Bay Rays (dome)
    14: (43.64155, -79.38915),  # Rogers Centre -- Toronto Blue Jays (retractable roof)
    15: (33.445302, -112.066687),  # Chase Field -- Arizona Diamondbacks (retractable roof)
    17: (41.948171, -87.655503),  # Wrigley Field -- Chicago Cubs
    19: (39.756042, -104.994136),  # Coors Field -- Colorado Rockies
    22: (34.07368, -118.24053),  # (Dodger Stadium) -- Los Angeles Dodgers
    31: (40.446904, -80.005753),  # PNC Park -- Pittsburgh Pirates
    32: (43.02838, -87.97099),  # American Family Field -- Milwaukee Brewers (retractable roof)
    680: (47.591333, -122.33251),  # T-Mobile Park -- Seattle Mariners (retractable roof)
    2392: (29.756967, -95.355509),  # Daikin Park -- Houston Astros (retractable roof)
    2394: (42.3391151, -83.048695),  # Comerica Park -- Detroit Tigers
    2395: (37.778383, -122.389448),  # Oracle Park -- San Francisco Giants
    2529: (38.57994, -121.51246),  # Sutter Health Park -- Athletics
    2602: (39.097389, -84.506611),  # Great American Ball Park -- Cincinnati Reds
    2680: (32.707861, -117.157278),  # Petco Park -- San Diego Padres
    2681: (39.90539086, -75.16716957),  # Citizens Bank Park -- Philadelphia Phillies
    2889: (38.62256667, -90.19286667),  # Busch Stadium -- St. Louis Cardinals
    3289: (40.75753012, -73.84559155),  # Citi Field -- New York Mets
    3309: (38.872861, -77.007501),  # Nationals Park -- Washington Nationals
    3312: (44.981829, -93.277891),  # Target Field -- Minnesota Twins
    3313: (40.82919482, -73.9264977),  # Yankee Stadium -- New York Yankees
    4169: (25.77796236, -80.21951795),  # loanDepot park -- Miami Marlins (retractable roof)
    4705: (33.890672, -84.467641),  # Truist Park -- Atlanta Braves
    5325: (32.747299, -97.081818),  # Globe Life Field -- Texas Rangers (retractable roof)
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
    record_label: str = "LIVE",
) -> RunSlateResult:
    if cutoff_at.tzinfo is None:
        raise ValueError("cutoff_at must be timezone-aware (UTC)")

    run_id = _new_run_id()
    client = http_client or httpx.Client(timeout=10.0)
    result = RunSlateResult(run_id=run_id, slate_date=slate_date, cutoff_at=cutoff_at)
    _start_run(session, run_id, slate_date)

    try:
        _stage(session, run_id, "INGEST", "running", started=True)
        result.ingest_results = ingest_slate(
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

        # ingest_slate() just wrote fresh raw_* rows stamped with real
        # wall-clock ingested_at (ADR 0001 -- ingested_at is always "now",
        # regardless of slate_date). If the caller's cutoff_at was
        # computed before that ingestion ran (the common case: "give me
        # a live run right now"), it can predate what was just written,
        # so every row would fail its ingested_at<=cutoff as-of filter
        # and FREEZE would silently see nothing. The effective freeze
        # cutoff is never earlier than "now, after ingestion" -- a
        # caller-supplied cutoff further in the future (e.g. the
        # integration tests' deliberate buffer) is still honored as-is.
        effective_cutoff = max(cutoff_at, datetime.now(UTC))
        result.cutoff_at = effective_cutoff

        _stage(session, run_id, "FREEZE", "running", started=True)
        snapshot, entries = build_snapshot(session, slate_date, effective_cutoff)
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
            i: build_features(e, effective_cutoff) for i, e in enumerate(projectable)
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
            if entry.probable is None:
                # Unreachable: `projectable` above already filtered these
                # out. Explicit check (not `assert`, which optimized
                # bytecode can strip) so this can never silently mis-key
                # a projection to the wrong pitcher.
                raise RuntimeError("projectable entry unexpectedly has no probable pitcher")
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
                as_of=effective_cutoff,
                publish=publish,
                record_label=record_label,
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


def ingest_slate(
    session: Session,
    slate_date: date,
    cutoff_at: datetime,
    client: httpx.Client | None = None,
    *,
    lines_drop_dir: Path | None = None,
    run_id: str | None = None,
) -> list[IngestResult]:
    """Runs every source adapter for one slate and writes their raw rows.
    Public (not `run_slate`-only) so it's independently callable -- e.g.
    the CLI's `ingest` command, for pulling fresh data without also
    freezing/projecting/publishing."""
    client = client or httpx.Client(timeout=10.0)
    run_id = run_id or _new_run_id()
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

    # Same reasoning as run_slate()'s effective_cutoff: the probable-
    # pitcher ingest just above wrote rows with real wall-clock
    # ingested_at, which can be later than a cutoff_at computed before
    # this function was called -- this lookup only needs "what did we
    # just ingest," so it always probes at least as late as right now.
    probe_cutoff = max(cutoff_at, datetime.now(UTC))
    games = games_for_slate_date(session, slate_date)
    probables: list[RawProbablePitcher] = []
    for game in games:
        probables.extend(
            all_as_of(session, RawProbablePitcher, {"mlb_game_pk": game.mlb_game_pk}, probe_cutoff)
        )
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

    # Real first-pitch time per venue, not the pipeline's run cutoff --
    # found and fixed after an external audit flagged that this
    # previously passed cutoff_at as the weather forecast target,
    # meaning the forecast was for "whenever this happened to run," not
    # for the actual game. Keyed by the EARLIEST game at that venue this
    # slate: correct for the (overwhelming majority) single-game case; a
    # doubleheader's second game reuses the first game's forecast time
    # rather than getting its own -- a real, documented limitation (see
    # CURRENT_STATE_AUDIT.md), not a silent one, since per-game weather
    # keying would also need pit/snapshot_builder.py's weather lookup to
    # stop being venue-only, a larger change left for later.
    our_venue_id_to_mlb_venue_id = {v.venue_id: v.mlb_venue_id for v in venues if v.mlb_venue_id is not None}
    earliest_game_time_by_mlb_venue_id: dict[int, datetime] = {}
    for game in games:
        if game.venue_id is None:
            continue
        mlb_vid = our_venue_id_to_mlb_venue_id.get(game.venue_id)
        if mlb_vid is None:
            continue
        current = earliest_game_time_by_mlb_venue_id.get(mlb_vid)
        if current is None or game.scheduled_start_utc < current:
            earliest_game_time_by_mlb_venue_id[mlb_vid] = game.scheduled_start_utc

    weather_venues = [
        {
            "venue_id": vid,
            "lat": VENUE_COORDINATES[vid][0],
            "lon": VENUE_COORDINATES[vid][1],
            "game_time_utc": earliest_game_time_by_mlb_venue_id.get(vid, cutoff_at),
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
        _ingest_lines(session, slate_date, cutoff_at, client, probables, games, lines_drop_dir, run_id)
    )

    return results


# The Odds API's free tier is a 500-requests/month budget -- one full
# slate's worth of odds calls (roughly one per game) already eats most of
# a day's fair share of that (500/30 ~= 16.6/day), so fetching it fresh on
# every one of the scheduler's several daily run_slate() calls would blow
# the month's quota in days, not weeks (see adapters/lines_odds_api.py's
# docstring). This throttle makes the metered odds fetch happen at most
# once per real calendar day regardless of how many times run_slate() is
# scheduled -- schedule/probables/weather still refresh on every
# configured run for freshness, only the quota-scarce vendor call is
# capped. Keyed off SourceHealth.last_success_at's calendar date (not
# slate_date) deliberately: The Odds API only ever has live/near-term
# events, never historical ones, so "already got real odds today" is a
# meaningful question for a live production run in a way it wouldn't be
# for a historical slate replay (which couldn't get real odds either way).
def _odds_api_already_succeeded_today(session: Session) -> bool:
    health = session.get(SourceHealth, LinesOddsApiAdapter.source_name)
    if health is None or health.last_success_at is None:
        return False
    today_local = datetime.now(UTC).astimezone(operating_tz()).date()
    return health.last_success_at.astimezone(operating_tz()).date() == today_local


def _ingest_lines(
    session: Session,
    slate_date: date,
    cutoff_at: datetime,
    client: httpx.Client,
    probables: list[RawProbablePitcher],
    games: list[Game],
    lines_drop_dir: Path | None,
    run_id: str,
) -> IngestResult:
    """Real odds vendor when configured (settings.odds_api_key -- see
    adapters/lines_odds_api.py), else the manual/fixture drop-folder
    stand-in (adapters/lines_manual.py). Same output contract either way,
    so nothing downstream cares which one ran."""
    if not settings.odds_api_key:
        return ingest(
            session,
            LinesManualAdapter(drop_dir=lines_drop_dir),
            slate_date=slate_date,
            as_of=cutoff_at,
            run_id=run_id,
        )

    if _odds_api_already_succeeded_today(session):
        return IngestResult(
            source_name=LinesOddsApiAdapter.source_name,
            records_written=0,
            is_available=True,
            warnings=[
                "Skipped: real odds already fetched successfully once today -- "
                "throttled to conserve the metered monthly quota"
            ],
        )

    player_mlb_ids = sorted({p.player_mlb_id for p in probables})
    names_by_mlb_id: dict[int, str] = {}
    if player_mlb_ids:
        rows = session.execute(select(Player).where(Player.mlb_person_id.in_(player_mlb_ids))).scalars()
        names_by_mlb_id = {r.mlb_person_id: r.full_name for r in rows if r.mlb_person_id is not None}

    probables_context = [
        {
            "player_mlb_id": p.player_mlb_id,
            "mlb_game_pk": p.mlb_game_pk,
            "full_name": names_by_mlb_id[p.player_mlb_id],
        }
        for p in probables
        if p.player_mlb_id in names_by_mlb_id
    ]
    relevant_game_pks = {p["mlb_game_pk"] for p in probables_context}
    game_start_times = [g.scheduled_start_utc for g in games if g.mlb_game_pk in relevant_game_pks]
    return ingest(
        session,
        LinesOddsApiAdapter(api_key=settings.odds_api_key, http_client=client),
        slate_date=slate_date,
        as_of=cutoff_at,
        run_id=run_id,
        probables=probables_context,
        game_start_times=game_start_times,
    )


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
