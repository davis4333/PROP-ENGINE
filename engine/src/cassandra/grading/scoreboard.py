"""The track-record scoreboard: today / last 7 days / last 30 days /
all-time, strictly LIVE-only (CLAUDE.md non-negotiable #8 and the mission
directive's explicit instruction never to silently mix DEMO/BACKTEST/
PAPER/SHADOW results into the real record). Distinct from
grading.tracker's resettable single-window counter -- this is the
permanent, un-resettable, multi-window view for the Admin page.

Windows are keyed by the GAME's slate date (ADR 0009's operating
timezone, config.slate_date_for) -- "today's record" means "games
scheduled today," matching how the Today/Ledger pages already define a
slate, not when a grade happened to be written.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from cassandra.config import operating_tz, slate_date_for
from cassandra.db.models.grading import Grade
from cassandra.db.models.identity import Game
from cassandra.db.models.projection import Projection
from cassandra.ledger.service import official_first_then_latest_version

SCOREBOARD_MODULE_VERSION = "grading-scoreboard-0.1.0"


@dataclass(frozen=True)
class WindowRecord:
    wins: int
    losses: int
    pushes: int
    voids: int
    no_plays: int
    # Real OVER/UNDER calls whose game hasn't produced a current grade
    # yet (not yet Final, or Final but not yet re-ingested/graded) --
    # distinct from a NO_PLAY grade result, which means the game DID
    # finish and Cassandra correctly declined to pick a side.
    waiting: int
    win_rate: float | None  # wins / (wins + losses); None when that's 0/0
    # Mean absolute error between projection_mean and actual_strikeouts,
    # over every graded row in this window that has both (any decision,
    # including NO_PLAY -- this measures projection accuracy, not bet
    # outcome). None when no row in the window has both values.
    mean_absolute_error: float | None
    projection_error_sample_size: int


@dataclass(frozen=True)
class Scoreboard:
    module_version: str
    as_of: datetime
    today: WindowRecord
    last_7_days: WindowRecord
    last_30_days: WindowRecord
    all_time: WindowRecord


@dataclass(frozen=True)
class _Row:
    slate_date: date
    decision: str
    result: str | None  # None when not yet graded
    projection_mean: float | None
    actual_strikeouts: int | None


def _fetch_live_rows(session: Session) -> list[_Row]:
    """Every CURRENT (official-first, latest-version) LIVE projection,
    left-joined to its current grade if one exists. The single source of
    truth this whole scoreboard is built from -- everything below is pure
    Python aggregation over this list, so the four windows can never
    disagree about which rows they're looking at."""
    base = select(Projection.logical_key, Projection.projection_id, Projection.version).where(
        Projection.record_label == "LIVE"
    )
    subq = official_first_then_latest_version(base).subquery()

    current_grade_ids = (
        select(Grade.projection_id, Grade.grade_id)
        .order_by(Grade.projection_id, Grade.graded_at.desc())
        .distinct(Grade.projection_id)
        .subquery()
    )

    stmt = (
        select(
            Game.scheduled_start_utc,
            Projection.decision,
            Grade.result,
            Projection.projection_mean,
            Grade.actual_strikeouts,
        )
        .select_from(Projection)
        .join(subq, Projection.projection_id == subq.c.projection_id)
        .join(Game, Game.game_id == Projection.game_id)
        .outerjoin(current_grade_ids, Projection.projection_id == current_grade_ids.c.projection_id)
        .outerjoin(Grade, Grade.grade_id == current_grade_ids.c.grade_id)
    )

    rows: list[_Row] = []
    for scheduled_start_utc, decision, result, projection_mean, actual_strikeouts in session.execute(stmt):
        rows.append(
            _Row(
                slate_date=slate_date_for(scheduled_start_utc),
                decision=decision,
                result=result,
                projection_mean=float(projection_mean) if projection_mean is not None else None,
                actual_strikeouts=actual_strikeouts,
            )
        )
    return rows


def _summarize(rows: list[_Row]) -> WindowRecord:
    wins = sum(1 for r in rows if r.result == "WIN")
    losses = sum(1 for r in rows if r.result == "LOSS")
    pushes = sum(1 for r in rows if r.result == "PUSH")
    voids = sum(1 for r in rows if r.result == "VOID")
    no_plays = sum(1 for r in rows if r.result == "NO_PLAY")
    waiting = sum(1 for r in rows if r.result is None and r.decision != "NO_PLAY")

    decided = wins + losses
    win_rate = wins / decided if decided > 0 else None

    errors = [
        abs(r.actual_strikeouts - r.projection_mean)
        for r in rows
        if r.actual_strikeouts is not None and r.projection_mean is not None
    ]
    mae = sum(errors) / len(errors) if errors else None

    return WindowRecord(
        wins=wins,
        losses=losses,
        pushes=pushes,
        voids=voids,
        no_plays=no_plays,
        waiting=waiting,
        win_rate=win_rate,
        mean_absolute_error=mae,
        projection_error_sample_size=len(errors),
    )


def build_scoreboard(session: Session) -> Scoreboard:
    now = datetime.now(UTC)
    today = now.astimezone(operating_tz()).date()
    rows = _fetch_live_rows(session)

    return Scoreboard(
        module_version=SCOREBOARD_MODULE_VERSION,
        as_of=now,
        today=_summarize([r for r in rows if r.slate_date == today]),
        last_7_days=_summarize([r for r in rows if today - timedelta(days=6) <= r.slate_date <= today]),
        last_30_days=_summarize([r for r in rows if today - timedelta(days=29) <= r.slate_date <= today]),
        all_time=_summarize(rows),
    )


__all__ = ["SCOREBOARD_MODULE_VERSION", "Scoreboard", "WindowRecord", "build_scoreboard"]
