"""orchestration/scheduler.py's pure gating logic and orchestration calls,
tested without a real database or network -- run_slate()/grade_slate_run()
and session_scope() are monkeypatched to fakes, so these exercise only the
scheduler's own decisions (when to trigger, what dates to grade, that one
failing call never blocks the others)."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import UTC, date, datetime

from cassandra.orchestration import scheduler


def test_should_trigger_run_true_after_hour_when_not_yet_run_today(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "auto_run_hour_local", 7)
    now = datetime(2026, 8, 5, 8, 0, tzinfo=UTC)
    assert scheduler.should_trigger_run(now, last_run_date=None) is True


def test_should_trigger_run_false_before_the_configured_hour(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "auto_run_hour_local", 7)
    now = datetime(2026, 8, 5, 6, 0, tzinfo=UTC)
    assert scheduler.should_trigger_run(now, last_run_date=None) is False


def test_should_trigger_run_false_when_already_run_today(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "auto_run_hour_local", 7)
    now = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
    assert scheduler.should_trigger_run(now, last_run_date=date(2026, 8, 5)) is False


def test_should_trigger_run_true_again_on_a_new_calendar_day(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "auto_run_hour_local", 7)
    now = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
    assert scheduler.should_trigger_run(now, last_run_date=date(2026, 8, 5)) is True


@contextmanager
def _fake_session_scope():
    yield object()


def test_run_scheduled_tasks_runs_slate_once_and_grades_the_lookback_window(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "auto_run_hour_local", 0)
    run_slate_calls: list[date] = []
    grade_calls: list[date] = []

    def fake_run_slate(session, slate_date, cutoff_at, *, http_client=None):
        run_slate_calls.append(slate_date)

    def fake_grade_slate_run(session, slate_date, *, http_client=None):
        grade_calls.append(slate_date)

    monkeypatch.setattr(scheduler, "run_slate", fake_run_slate)
    monkeypatch.setattr(scheduler, "grade_slate_run", fake_grade_slate_run)
    monkeypatch.setattr(scheduler, "session_scope", _fake_session_scope)
    monkeypatch.setattr(scheduler, "_run_slate_already_succeeded_today", lambda session, today: False)

    now = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    last_run_date = scheduler.run_scheduled_tasks(now, last_run_date=None)

    assert run_slate_calls == [date(2026, 8, 5)]
    assert grade_calls == [
        date(2026, 8, 5),
        date(2026, 8, 4),
        date(2026, 8, 3),
        date(2026, 8, 2),
    ]
    assert last_run_date == date(2026, 8, 5)


def test_run_scheduled_tasks_skips_run_slate_but_still_grades_when_already_run_today(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "auto_run_hour_local", 0)
    run_slate_calls: list[date] = []
    grade_calls: list[date] = []
    monkeypatch.setattr(
        scheduler, "run_slate", lambda *a, **k: run_slate_calls.append(a[1])
    )
    monkeypatch.setattr(
        scheduler, "grade_slate_run", lambda *a, **k: grade_calls.append(a[1])
    )
    monkeypatch.setattr(scheduler, "session_scope", _fake_session_scope)
    monkeypatch.setattr(scheduler, "_run_slate_already_succeeded_today", lambda session, today: False)

    now = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    last_run_date = scheduler.run_scheduled_tasks(now, last_run_date=date(2026, 8, 5))

    assert run_slate_calls == []
    assert grade_calls  # grading is re-attempted regardless
    assert last_run_date == date(2026, 8, 5)


def test_run_scheduled_tasks_grading_still_runs_after_run_slate_raises(monkeypatch):
    # A failed run_slate() (e.g. the live MLB API is briefly down) must
    # never take down the background thread or block grading of already-
    # published projections from earlier runs.
    monkeypatch.setattr(scheduler.settings, "auto_run_hour_local", 0)
    grade_calls: list[date] = []

    def raising_run_slate(*a, **k):
        raise RuntimeError("simulated upstream failure")

    monkeypatch.setattr(scheduler, "run_slate", raising_run_slate)
    monkeypatch.setattr(
        scheduler, "grade_slate_run", lambda *a, **k: grade_calls.append(a[1])
    )
    monkeypatch.setattr(scheduler, "session_scope", _fake_session_scope)
    monkeypatch.setattr(scheduler, "_run_slate_already_succeeded_today", lambda session, today: False)

    now = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    last_run_date = scheduler.run_scheduled_tasks(now, last_run_date=None)

    assert grade_calls
    assert last_run_date == date(2026, 8, 5)


def test_run_scheduled_tasks_one_failing_grade_date_does_not_block_the_others(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "auto_run_hour_local", 0)
    grade_calls: list[date] = []

    def sometimes_raising_grade(session, slate_date, *, http_client=None):
        if slate_date == date(2026, 8, 4):
            raise RuntimeError("simulated failure grading one day")
        grade_calls.append(slate_date)

    monkeypatch.setattr(scheduler, "run_slate", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "grade_slate_run", sometimes_raising_grade)
    monkeypatch.setattr(scheduler, "session_scope", _fake_session_scope)
    monkeypatch.setattr(scheduler, "_run_slate_already_succeeded_today", lambda session, today: False)

    now = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    scheduler.run_scheduled_tasks(now, last_run_date=None)

    assert date(2026, 8, 4) not in grade_calls
    assert date(2026, 8, 5) in grade_calls
    assert date(2026, 8, 3) in grade_calls


def test_run_scheduled_tasks_skips_run_slate_when_db_shows_it_already_succeeded_today(monkeypatch):
    # Regression for a real gap found by an architecture review:
    # last_run_date is only an in-memory variable, reset to None on every
    # process restart. Without reconciling against the DB, a redeploy
    # after today's real run_slate() already succeeded would trigger a
    # redundant one, re-burning real, metered Odds API credits for no
    # new information.
    monkeypatch.setattr(scheduler.settings, "auto_run_hour_local", 0)
    run_slate_calls: list[date] = []
    monkeypatch.setattr(scheduler, "run_slate", lambda *a, **k: run_slate_calls.append(a[1]))
    monkeypatch.setattr(scheduler, "grade_slate_run", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "session_scope", _fake_session_scope)
    monkeypatch.setattr(scheduler, "_run_slate_already_succeeded_today", lambda session, today: True)

    now = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    # last_run_date=None simulates a fresh process (just restarted/redeployed)
    last_run_date = scheduler.run_scheduled_tasks(now, last_run_date=None)

    assert run_slate_calls == []
    assert last_run_date == date(2026, 8, 5)


def test_run_scheduled_tasks_still_runs_when_db_shows_no_prior_success_today(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "auto_run_hour_local", 0)
    run_slate_calls: list[date] = []
    monkeypatch.setattr(scheduler, "run_slate", lambda *a, **k: run_slate_calls.append(a[1]))
    monkeypatch.setattr(scheduler, "grade_slate_run", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "session_scope", _fake_session_scope)
    monkeypatch.setattr(scheduler, "_run_slate_already_succeeded_today", lambda session, today: False)

    now = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    last_run_date = scheduler.run_scheduled_tasks(now, last_run_date=None)

    assert run_slate_calls == [date(2026, 8, 5)]
    assert last_run_date == date(2026, 8, 5)


def test_db_reconciliation_is_skipped_once_last_run_date_already_matches_today(monkeypatch):
    # Once the in-memory flag already agrees with today, no need to hit
    # the DB again on every 15-minute tick just to re-confirm it.
    monkeypatch.setattr(scheduler.settings, "auto_run_hour_local", 0)
    check_calls: list[date] = []

    def fake_check(session, today):
        check_calls.append(today)
        return False

    monkeypatch.setattr(scheduler, "run_slate", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "grade_slate_run", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "session_scope", _fake_session_scope)
    monkeypatch.setattr(scheduler, "_run_slate_already_succeeded_today", fake_check)

    now = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    scheduler.run_scheduled_tasks(now, last_run_date=date(2026, 8, 5))

    assert check_calls == []


def test_start_background_scheduler_is_a_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "auto_scheduler_enabled", False)
    stop_event = scheduler.start_background_scheduler()
    assert stop_event.is_set()


def test_start_background_scheduler_starts_a_daemon_thread_when_enabled(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "auto_scheduler_enabled", True)
    loop_started = threading.Event()

    def fake_loop(stop_event: threading.Event) -> None:
        loop_started.set()
        stop_event.wait()

    monkeypatch.setattr(scheduler, "_scheduler_loop", fake_loop)
    stop_event = scheduler.start_background_scheduler()
    try:
        assert loop_started.wait(timeout=2), "background thread never started"
    finally:
        stop_event.set()
