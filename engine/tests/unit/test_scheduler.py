"""orchestration/scheduler.py's pure gating logic and orchestration calls,
tested without a real database or network -- run_slate()/grade_slate_run()
and session_scope() are monkeypatched to fakes, so these exercise only the
scheduler's own decisions (when to trigger, what dates to grade, that one
failing call never blocks the others). The DB-backed restart-safety logic
itself (_run_slate_success_count_today's actual SQL) is proven separately
against a real Postgres session in
tests/integration/test_scheduler_reconciliation.py."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import UTC, date, datetime

from cassandra.orchestration import scheduler


def test_parse_run_hours_sorts_and_dedupes():
    assert scheduler.parse_run_hours("16,7,12,7") == [7, 12, 16]


def test_parse_run_hours_skips_unparseable_entries(caplog):
    assert scheduler.parse_run_hours("7,not-a-number,16") == [7, 16]


def test_parse_run_hours_skips_out_of_range_entries():
    assert scheduler.parse_run_hours("7,24,-1,16") == [7, 16]


def test_parse_run_hours_falls_back_to_default_when_nothing_valid():
    assert scheduler.parse_run_hours("garbage,,25") == [7]


def test_should_trigger_run_true_when_one_hour_passed_and_zero_succeeded():
    now = datetime(2026, 8, 5, 8, 0, tzinfo=UTC)
    assert scheduler.should_trigger_run(now, [7], already_succeeded_today=0) is True


def test_should_trigger_run_false_before_any_configured_hour():
    now = datetime(2026, 8, 5, 6, 0, tzinfo=UTC)
    assert scheduler.should_trigger_run(now, [7, 12, 16], already_succeeded_today=0) is False


def test_should_trigger_run_false_when_successes_already_match_hours_passed():
    now = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
    assert scheduler.should_trigger_run(now, [7], already_succeeded_today=1) is False


def test_should_trigger_run_true_again_once_a_second_configured_hour_passes():
    now = datetime(2026, 8, 5, 12, 30, tzinfo=UTC)
    # 07:00 and 12:00 have both passed (2 due), but only 1 success so far
    assert scheduler.should_trigger_run(now, [7, 12, 16], already_succeeded_today=1) is True


def test_should_trigger_run_false_once_all_passed_hours_are_covered():
    now = datetime(2026, 8, 5, 13, 0, tzinfo=UTC)
    assert scheduler.should_trigger_run(now, [7, 12, 16], already_succeeded_today=2) is False


@contextmanager
def _fake_session_scope():
    yield object()


def test_run_scheduled_tasks_runs_slate_and_grades_the_lookback_window(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "auto_run_hours_local", "0")
    run_slate_calls: list[date] = []
    grade_calls: list[date] = []

    def fake_run_slate(session, slate_date, cutoff_at, *, http_client=None):
        run_slate_calls.append(slate_date)

    def fake_grade_slate_run(session, slate_date, *, http_client=None):
        grade_calls.append(slate_date)

    monkeypatch.setattr(scheduler, "run_slate", fake_run_slate)
    monkeypatch.setattr(scheduler, "grade_slate_run", fake_grade_slate_run)
    monkeypatch.setattr(scheduler, "session_scope", _fake_session_scope)
    monkeypatch.setattr(scheduler, "_run_slate_success_count_today", lambda session, today: 0)

    now = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    scheduler.run_scheduled_tasks(now)

    assert run_slate_calls == [date(2026, 8, 5)]
    assert grade_calls == [
        date(2026, 8, 5),
        date(2026, 8, 4),
        date(2026, 8, 3),
        date(2026, 8, 2),
    ]


def test_run_scheduled_tasks_skips_run_slate_but_still_grades_when_already_covered(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "auto_run_hours_local", "0")
    run_slate_calls: list[date] = []
    grade_calls: list[date] = []
    monkeypatch.setattr(scheduler, "run_slate", lambda *a, **k: run_slate_calls.append(a[1]))
    monkeypatch.setattr(scheduler, "grade_slate_run", lambda *a, **k: grade_calls.append(a[1]))
    monkeypatch.setattr(scheduler, "session_scope", _fake_session_scope)
    # one configured hour (0), one already-successful run today -> covered
    monkeypatch.setattr(scheduler, "_run_slate_success_count_today", lambda session, today: 1)

    now = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    scheduler.run_scheduled_tasks(now)

    assert run_slate_calls == []
    assert grade_calls  # grading is re-attempted regardless


def test_run_scheduled_tasks_triggers_a_second_run_once_a_later_hour_passes(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "auto_run_hours_local", "7,12,16")
    run_slate_calls: list[date] = []
    monkeypatch.setattr(scheduler, "run_slate", lambda *a, **k: run_slate_calls.append(a[1]))
    monkeypatch.setattr(scheduler, "grade_slate_run", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "session_scope", _fake_session_scope)
    # 07:00's run already happened once; now it's past 12:00 too
    monkeypatch.setattr(scheduler, "_run_slate_success_count_today", lambda session, today: 1)

    now = datetime(2026, 8, 5, 12, 30, tzinfo=UTC)
    scheduler.run_scheduled_tasks(now)

    assert run_slate_calls == [date(2026, 8, 5)]


def test_run_scheduled_tasks_grading_still_runs_after_run_slate_raises(monkeypatch):
    # A failed run_slate() (e.g. the live MLB API is briefly down) must
    # never take down the background thread or block grading of already-
    # published projections from earlier runs.
    monkeypatch.setattr(scheduler.settings, "auto_run_hours_local", "0")
    grade_calls: list[date] = []

    def raising_run_slate(*a, **k):
        raise RuntimeError("simulated upstream failure")

    monkeypatch.setattr(scheduler, "run_slate", raising_run_slate)
    monkeypatch.setattr(scheduler, "grade_slate_run", lambda *a, **k: grade_calls.append(a[1]))
    monkeypatch.setattr(scheduler, "session_scope", _fake_session_scope)
    monkeypatch.setattr(scheduler, "_run_slate_success_count_today", lambda session, today: 0)

    now = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    scheduler.run_scheduled_tasks(now)

    assert grade_calls


def test_run_scheduled_tasks_one_failing_grade_date_does_not_block_the_others(monkeypatch):
    monkeypatch.setattr(scheduler.settings, "auto_run_hours_local", "0")
    grade_calls: list[date] = []

    def sometimes_raising_grade(session, slate_date, *, http_client=None):
        if slate_date == date(2026, 8, 4):
            raise RuntimeError("simulated failure grading one day")
        grade_calls.append(slate_date)

    monkeypatch.setattr(scheduler, "run_slate", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "grade_slate_run", sometimes_raising_grade)
    monkeypatch.setattr(scheduler, "session_scope", _fake_session_scope)
    monkeypatch.setattr(scheduler, "_run_slate_success_count_today", lambda session, today: 0)

    now = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    scheduler.run_scheduled_tasks(now)

    assert date(2026, 8, 4) not in grade_calls
    assert date(2026, 8, 5) in grade_calls
    assert date(2026, 8, 3) in grade_calls


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
