"""orchestration/scheduler.py's _run_scheduled_tasks_locked() -- Phase 2C's
defense against two scheduler processes somehow running against the same
database at once. Uses a real Postgres connection (the advisory lock is a
genuine server-side primitive, not something a mock session can exercise)
independent of the db_session fixture's transaction, since
pg_advisory_lock is a session-level, not transaction-level, primitive."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime

from sqlalchemy import text

from cassandra.db.session import engine
from cassandra.orchestration import scheduler

NOW = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)


def test_locked_wrapper_runs_the_tick_when_the_lock_is_free(monkeypatch):
    calls: list[datetime] = []
    monkeypatch.setattr(scheduler, "run_scheduled_tasks", calls.append)

    scheduler._run_scheduled_tasks_locked(NOW)

    assert calls == [NOW]


def test_locked_wrapper_skips_the_tick_when_another_connection_holds_the_lock(monkeypatch):
    calls: list[datetime] = []
    monkeypatch.setattr(scheduler, "run_scheduled_tasks", calls.append)

    with engine.connect() as holder_conn:
        holder_conn.execute(
            text("SELECT pg_advisory_lock(:key)"), {"key": scheduler._SCHEDULER_ADVISORY_LOCK_KEY}
        )
        try:
            scheduler._run_scheduled_tasks_locked(NOW)
            assert calls == []
        finally:
            holder_conn.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": scheduler._SCHEDULER_ADVISORY_LOCK_KEY}
            )


def test_locked_wrapper_releases_the_lock_so_a_later_call_can_reacquire_it(monkeypatch):
    calls: list[datetime] = []
    monkeypatch.setattr(scheduler, "run_scheduled_tasks", calls.append)

    scheduler._run_scheduled_tasks_locked(NOW)
    scheduler._run_scheduled_tasks_locked(NOW)

    assert calls == [NOW, NOW]


def test_locked_wrapper_releases_the_lock_even_when_the_tick_raises(monkeypatch):
    # run_scheduled_tasks() itself is documented never to raise, but the
    # lock release must not depend on that -- a future bug there
    # shouldn't also leak the advisory lock forever.
    def raising_tick(now: datetime) -> None:
        raise RuntimeError("simulated unexpected failure")

    monkeypatch.setattr(scheduler, "run_scheduled_tasks", raising_tick)

    with contextlib.suppress(RuntimeError):
        scheduler._run_scheduled_tasks_locked(NOW)

    # If the lock leaked, this second call would see it already held by
    # this same session -- but pg_try_advisory_lock is re-entrant within
    # the SAME session/connection, so the real proof is a fresh
    # connection can now acquire it (meaning the first connection
    # released it before closing).
    with engine.connect() as probe_conn:
        acquired = probe_conn.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": scheduler._SCHEDULER_ADVISORY_LOCK_KEY}
        ).scalar_one()
        try:
            assert acquired is True
        finally:
            if acquired:
                probe_conn.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": scheduler._SCHEDULER_ADVISORY_LOCK_KEY}
                )
