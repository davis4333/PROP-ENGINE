"""Freezes a point-in-time view of a slate: for every game whose calendar
slate-date (ADR 0009) matches `slate_date`, resolves the latest-as-of-
cutoff probable pitcher(s), their recent game logs, park factor, weather,
lines, and umpire availability -- purely via `pit/asof.py`, never a
direct raw-table query. Writes `snapshot_raw_refs` for every raw_* row
actually included (the audit trail) and `snapshot_data_quality` for
every `ingestion.quality_gate` finding.

Rerunning for the same `(slate_date, cutoff_at)` never mutates a prior
snapshot -- it always creates a new `Snapshot` row (immutable once
frozen; see ADR 0001).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from cassandra.config import slate_date_for
from cassandra.db.models.identity import Game, Team
from cassandra.db.models.raw import (
    RawLine,
    RawParkFactor,
    RawPitcherGameLog,
    RawProbablePitcher,
    RawWeatherObservation,
)
from cassandra.db.models.snapshot import Snapshot, SnapshotDataQuality, SnapshotRawRef
from cassandra.ingestion.quality_gate import (
    QualityFinding,
    check_data_stale,
    check_line_available,
    check_line_conflict,
    check_starter_confirmed,
)
from cassandra.pit.asof import all_as_of, latest_as_of, latest_grouped_as_of

STRIKEOUT_MARKET = "pitcher_strikeouts"
UMPIRE_UNAVAILABLE_FINDING = QualityFinding(
    "DATA_MISSING",
    "No reliable free umpire-assignment source is available (permanent stub); "
    "umpire context is not included in this or any snapshot.",
    "warn",
)


@dataclass
class PitcherSlateEntry:
    game: Game
    team_mlb_id: int
    probable: RawProbablePitcher | None
    game_logs: list[RawPitcherGameLog]
    park_factor: RawParkFactor | None
    weather: RawWeatherObservation | None
    lines: list[RawLine]
    quality_findings: list[QualityFinding] = field(default_factory=list)


def build_snapshot(
    session: Session, slate_date: date, cutoff_at: datetime
) -> tuple[Snapshot, list[PitcherSlateEntry]]:
    if cutoff_at.tzinfo is None:
        raise ValueError("cutoff_at must be timezone-aware (UTC)")

    snapshot = Snapshot(slate_date=slate_date, cutoff_at=cutoff_at, status="building")
    session.add(snapshot)
    session.flush()  # assign snapshot_id

    games = games_for_slate_date(session, slate_date)
    entries: list[PitcherSlateEntry] = []
    # A game-level fact (park factor, weather) is referenced once per
    # team/pitcher below; dedupe so the same (raw_table, raw_id) isn't
    # inserted into snapshot_raw_refs twice for one snapshot.
    seen_refs: set[tuple[str, object]] = set()

    for game in games:
        probables = latest_grouped_as_of(
            session,
            RawProbablePitcher,
            {"mlb_game_pk": game.mlb_game_pk},
            cutoff_at,
            group_by="team_mlb_id",
        )
        mlb_team_ids = _mlb_team_ids(session, {game.home_team_id, game.away_team_id})

        for team_mlb_id in mlb_team_ids:
            probable = next((p for p in probables if p.team_mlb_id == team_mlb_id), None)
            findings: list[QualityFinding] = []

            starter_finding = check_starter_confirmed(probable)
            if starter_finding:
                findings.append(starter_finding)

            game_logs: list[RawPitcherGameLog] = []
            park_factor: RawParkFactor | None = None
            weather: RawWeatherObservation | None = None
            lines: list[RawLine] = []

            if probable is not None:
                _ref(
                    session,
                    seen_refs,
                    snapshot.snapshot_id,
                    "raw_probable_pitchers",
                    probable.raw_id,
                    f"mlb_game_pk={game.mlb_game_pk},team_mlb_id={team_mlb_id}",
                )
                stale = check_data_stale(probable.observed_at, cutoff_at, "Probable pitcher")
                if stale:
                    findings.append(stale)

                game_logs = all_as_of(
                    session,
                    RawPitcherGameLog,
                    {"player_mlb_id": probable.player_mlb_id},
                    cutoff_at,
                )
                for gl in game_logs:
                    _ref(
                        session,
                        seen_refs,
                        snapshot.snapshot_id,
                        "raw_pitcher_game_logs",
                        gl.raw_id,
                        f"player_mlb_id={probable.player_mlb_id},stat_date={gl.stat_date}",
                    )

                lines = all_as_of(
                    session,
                    RawLine,
                    {
                        "mlb_game_pk": game.mlb_game_pk,
                        "player_mlb_id": probable.player_mlb_id,
                        "market": STRIKEOUT_MARKET,
                    },
                    cutoff_at,
                )
                for line in lines:
                    _ref(
                        session,
                        seen_refs,
                        snapshot.snapshot_id,
                        "raw_lines",
                        line.raw_id,
                        f"player_mlb_id={probable.player_mlb_id},market={STRIKEOUT_MARKET}",
                    )
                line_finding = check_line_available(lines)
                if line_finding:
                    findings.append(line_finding)
                conflict_finding = check_line_conflict(lines)
                if conflict_finding:
                    findings.append(conflict_finding)

            if game.venue_id:
                park_factor = latest_as_of(
                    session,
                    RawParkFactor,
                    {"venue_id": game.venue_id, "season": slate_date.year},
                    cutoff_at,
                )
                if park_factor:
                    _ref(
                        session,
                        seen_refs,
                        snapshot.snapshot_id,
                        "raw_park_factors",
                        park_factor.raw_id,
                        f"venue_id={game.venue_id}",
                    )
                weather = latest_as_of(session, RawWeatherObservation, {"venue_id": game.venue_id}, cutoff_at)
                if weather:
                    _ref(
                        session,
                        seen_refs,
                        snapshot.snapshot_id,
                        "raw_weather_observations",
                        weather.raw_id,
                        f"venue_id={game.venue_id}",
                    )

            findings.append(UMPIRE_UNAVAILABLE_FINDING)

            for finding in findings:
                session.add(
                    SnapshotDataQuality(
                        snapshot_id=snapshot.snapshot_id,
                        check_name=finding.reason_code.lower(),
                        status=finding.status,
                        reason_code=finding.reason_code,
                        detail=finding.detail,
                    )
                )

            entries.append(
                PitcherSlateEntry(
                    game=game,
                    team_mlb_id=team_mlb_id,
                    probable=probable,
                    game_logs=game_logs,
                    park_factor=park_factor,
                    weather=weather,
                    lines=lines,
                    quality_findings=findings,
                )
            )

    snapshot.status = "frozen"
    return snapshot, entries


def games_for_slate_date(session: Session, slate_date: date) -> list[Game]:
    """Games are stored with a UTC scheduled_start_utc; slate membership
    is derived via config.slate_date_for (ADR 0009), not a raw date
    match, since a UTC calendar day can span two operating-timezone
    slate-dates. Query a generous UTC window, then filter precisely in
    Python.

    Public (not `_`-prefixed): shared with orchestration/run_slate.py,
    which needs "which games are in this slate" during INGEST, before a
    snapshot exists to derive it from."""
    window_start = datetime.combine(slate_date, time.min, tzinfo=UTC) - timedelta(days=1)
    window_end = window_start + timedelta(days=3)
    stmt = select(Game).where(Game.scheduled_start_utc >= window_start, Game.scheduled_start_utc < window_end)
    candidates = session.execute(stmt).scalars().all()
    return [g for g in candidates if slate_date_for(g.scheduled_start_utc) == slate_date]


def _mlb_team_ids(session: Session, team_ids: set[str | None]) -> list[int]:
    ids = [t for t in team_ids if t is not None]
    if not ids:
        return []
    rows = session.execute(select(Team).where(Team.team_id.in_(ids))).scalars().all()
    return [r.mlb_team_id for r in rows if r.mlb_team_id is not None]


def _ref(
    session: Session,
    seen_refs: set[tuple[str, object]],
    snapshot_id: object,
    raw_table: str,
    raw_id: object,
    natural_key: str,
) -> None:
    key = (raw_table, raw_id)
    if key in seen_refs:
        return
    seen_refs.add(key)
    session.add(
        SnapshotRawRef(snapshot_id=snapshot_id, raw_table=raw_table, raw_id=raw_id, natural_key=natural_key)
    )
