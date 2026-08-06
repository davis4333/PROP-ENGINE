"""Best-effort in-process scheduler so a long-running deployment (e.g. the
single Replit process scripts/replit_start.sh starts) populates Today and
grades recent slates without a human running the CLI by hand.

This is deliberately not a distributed job queue or a real cron -- one
process, one background thread, checked on a coarse poll interval.
Missing a tick (a process restart, a Repl going to sleep) just means the
next tick catches up; nothing here is safety- or correctness-critical the
way the pipeline itself is -- run_slate() and grade_slate_run() are
already idempotent/safe to call repeatedly (append-only ledger
versioning, ADR 0007's idempotent grading, and ledger/service.py's
official-vs-late-publication precedence), so "ran twice" and "ran late"
are both harmless, never a leakage or duplication risk.

Two different cadences, deliberately:
  - run_slate() fires once per configured local hour in
    settings.auto_run_hours_local (a comma-separated list, e.g. "7,12,16"
    for a morning/midday/pre-evening-game refresh) -- catching newly
    confirmed starters, updated lines, and weather throughout the day,
    not just once at a single fixed morning hour. A run that happens to
    land after a given game's first pitch is still correctly excluded
    from being that game's official/current record (ledger/service.py),
    so adding more daily runs only ever adds freshness, never risks
    silently overwriting an honest earlier pick.
  - grade_slate_run() is re-attempted every poll tick for a trailing
    window of days -- games finish (and box scores become available) at
    unpredictable times through the evening, and grading is cheap and
    fully idempotent, so checking often costs nothing and catches Finals
    promptly.

Restart-safety for the run_slate() cadence is DB-backed, not in-memory:
each tick counts how many of today's configured hours have already
passed and compares that against how many real run_slate() successes
are actually on record for today (see _run_slate_success_count_today) --
a process restart just re-derives this count from the database, so a
redeploy can never trigger a redundant run (re-burning real, metered
Odds API credits) just because in-memory state was reset to zero.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cassandra.config import operating_tz, settings
from cassandra.db.models.pipeline import PipelineRun, PipelineRunStage
from cassandra.db.session import session_scope
from cassandra.orchestration.run_slate import grade_slate_run, run_slate

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 15 * 60
GRADE_LOOKBACK_DAYS = 3


def _local_now() -> datetime:
    return datetime.now(UTC).astimezone(operating_tz())


def parse_run_hours(raw: str) -> list[int]:
    """settings.auto_run_hours_local ("7,12,16") -> sorted distinct hours
    (0-23). Never raises on bad input -- an unparseable entry is skipped
    (visible via a WARNING log), not a startup crash; falls back to a
    single default hour if nothing valid remains."""
    hours: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            hour = int(part)
        except ValueError:
            logger.warning("scheduler: ignoring unparseable hour %r in AUTO_RUN_HOURS_LOCAL", part)
            continue
        if 0 <= hour <= 23:
            hours.add(hour)
        else:
            logger.warning("scheduler: ignoring out-of-range hour %r in AUTO_RUN_HOURS_LOCAL", part)
    return sorted(hours) if hours else [7]


def should_trigger_run(
    now_local: datetime, configured_hours: list[int], already_succeeded_today: int
) -> bool:
    """Pure gating rule for the run_slate() trigger, split out from the
    sleep loop so it's testable without real threads/clocks/DB. True
    whenever more of today's configured hours have passed than we have
    recorded real successes for -- generalizes cleanly from "once a day"
    (one configured hour) to N times a day without needing to track
    which specific hour slot each success belongs to."""
    hours_due = sum(1 for h in configured_hours if now_local.hour >= h)
    return hours_due > already_succeeded_today


def _run_slate_success_count_today(session: Session, today: date) -> int:
    """Counts real run_slate() successes on record for today, to compare
    against how many of today's configured hours have passed.
    Distinguishes a real run_slate() from a grade_slate_run()-only
    PipelineRun for the same slate_date -- both write a PipelineRun row,
    but only run_slate() ever marks PUBLISH as anything other than
    "skipped" (grade_slate_run() always marks it skipped, detail "Not
    part of grade_slate_run").

    Requires BOTH `PipelineRun.status == "succeeded"` AND
    `PipelineRunStage(stage="PUBLISH").status == "succeeded"` -- found and
    fixed after an audit: the previous query only checked
    `PipelineRunStage.status != "skipped"`, which counts "running" (a
    crashed/interrupted run stuck mid-stage) and "failed" as if they were
    successful completions. That bug was effectively unobservable before
    orchestration/run_slate.py's own durable-failed-run fix (a failed run
    used to leave zero trace at all, so there was nothing for this query
    to miscount) -- now that a failed run genuinely leaves a `status=
    "failed"` `PipelineRunStage(stage="PUBLISH")` row, undercounting it as
    a real success would suppress a legitimate retry for that hour slot,
    silently leaving a slate un-run for the rest of the day."""
    stmt = (
        select(func.count(func.distinct(PipelineRunStage.run_id)))
        .join(PipelineRun, PipelineRun.run_id == PipelineRunStage.run_id)
        .where(
            PipelineRun.slate_date == today,
            PipelineRun.status == "succeeded",
            PipelineRunStage.stage == "PUBLISH",
            PipelineRunStage.status == "succeeded",
        )
    )
    return session.execute(stmt).scalar_one()


def run_scheduled_tasks(now_local: datetime) -> None:
    """Runs whichever of run_slate()/grade_slate_run() are due at
    `now_local`, catching and logging (never raising) so one bad tick
    can't kill the background thread."""
    today = now_local.date()
    configured_hours = parse_run_hours(settings.auto_run_hours_local)

    with httpx.Client(timeout=10.0) as client:
        with session_scope() as session:
            already_succeeded = _run_slate_success_count_today(session, today)

        if should_trigger_run(now_local, configured_hours, already_succeeded):
            try:
                with session_scope() as session:
                    run_slate(session, today, datetime.now(UTC), http_client=client)
                logger.info("scheduler: run_slate succeeded for %s", today)
            except Exception:
                logger.exception("scheduler: run_slate failed for %s", today)

        for offset in range(GRADE_LOOKBACK_DAYS + 1):
            target = today - timedelta(days=offset)
            try:
                with session_scope() as session:
                    grade_slate_run(session, target, http_client=client)
            except Exception:
                logger.exception("scheduler: grade_slate_run failed for %s", target)


def _scheduler_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        run_scheduled_tasks(_local_now())
        stop_event.wait(POLL_INTERVAL_SECONDS)


def start_background_scheduler() -> threading.Event:
    """Starts the scheduler as a daemon thread when
    settings.auto_scheduler_enabled is set; returns a stop Event the
    caller (FastAPI's lifespan shutdown) signals to exit cleanly. Returns
    an already-set Event with no thread started when disabled, so callers
    never need an `if enabled:` branch of their own."""
    stop_event = threading.Event()
    if not settings.auto_scheduler_enabled:
        stop_event.set()
        return stop_event
    thread = threading.Thread(
        target=_scheduler_loop, args=(stop_event,), daemon=True, name="cassandra-scheduler"
    )
    thread.start()
    return stop_event
