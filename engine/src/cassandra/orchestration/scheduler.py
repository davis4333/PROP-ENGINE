"""Best-effort in-process daily scheduler so a long-running deployment
(e.g. the single Replit process scripts/replit_start.sh starts) populates
Today and grades recent slates without a human running the CLI by hand.

This is deliberately not a distributed job queue or a real cron -- one
process, one background thread, checked on a coarse poll interval.
Missing a tick (a process restart, a Repl going to sleep) just means the
next tick catches up; nothing here is safety- or correctness-critical the
way the pipeline itself is -- run_slate() and grade_slate_run() are
already idempotent/safe to call repeatedly (append-only ledger
versioning, ADR 0007's idempotent grading), so "ran twice" and "ran late"
are both harmless, never a leakage or duplication risk.

Two different cadences, deliberately:
  - run_slate() fires once per local calendar day (settings.auto_run_hour_local)
    -- there is exactly one "today" to project, and re-running it more
    often than that just adds projection versions without new information
    (probable pitchers are typically confirmed by mid-morning).
  - grade_slate_run() is re-attempted every poll tick for a trailing
    window of days -- games finish (and box scores become available) at
    unpredictable times through the evening, and grading is cheap and
    fully idempotent, so checking often costs nothing and catches Finals
    promptly.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, date, datetime, timedelta

import httpx

from cassandra.config import operating_tz, settings
from cassandra.db.session import session_scope
from cassandra.orchestration.run_slate import grade_slate_run, run_slate

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 15 * 60
GRADE_LOOKBACK_DAYS = 3


def _local_now() -> datetime:
    return datetime.now(UTC).astimezone(operating_tz())


def should_trigger_run(now_local: datetime, last_run_date: date | None) -> bool:
    """Pure gating rule for the once-per-day run_slate() trigger, split
    out from the sleep loop so it's testable without real threads/clocks."""
    return now_local.hour >= settings.auto_run_hour_local and last_run_date != now_local.date()


def run_scheduled_tasks(now_local: datetime, last_run_date: date | None) -> date | None:
    """Runs whichever of run_slate()/grade_slate_run() are due at
    `now_local`, catching and logging (never raising) so one bad tick
    can't kill the background thread. Returns the last_run_date the
    caller's loop should carry forward."""
    client = httpx.Client(timeout=10.0)
    today = now_local.date()

    if should_trigger_run(now_local, last_run_date):
        try:
            with session_scope() as session:
                run_slate(session, today, datetime.now(UTC), http_client=client)
            logger.info("scheduler: run_slate succeeded for %s", today)
        except Exception:
            logger.exception("scheduler: run_slate failed for %s", today)
        last_run_date = today

    for offset in range(GRADE_LOOKBACK_DAYS + 1):
        target = today - timedelta(days=offset)
        try:
            with session_scope() as session:
                grade_slate_run(session, target, http_client=client)
        except Exception:
            logger.exception("scheduler: grade_slate_run failed for %s", target)

    return last_run_date


def _scheduler_loop(stop_event: threading.Event) -> None:
    last_run_date: date | None = None
    while not stop_event.is_set():
        last_run_date = run_scheduled_tasks(_local_now(), last_run_date)
        stop_event.wait(POLL_INTERVAL_SECONDS)


def start_background_scheduler() -> threading.Event:
    """Starts the daily scheduler as a daemon thread when
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
