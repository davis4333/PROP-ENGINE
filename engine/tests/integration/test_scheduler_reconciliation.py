"""orchestration/scheduler.py's _run_slate_success_count_today() against a
real Postgres session -- proves the actual SQL correctly tells a real
run_slate() PipelineRun apart from a grade_slate_run()-only one for the
same slate_date (both write a PipelineRun row; only run_slate() ever
marks PUBLISH as anything other than "skipped"), and counts distinct
real successes correctly (needed for the multiple-runs-per-day cadence,
not just a yes/no check).

Also covers a real bug found by an independent audit: the query used to
only check `PipelineRunStage.status != "skipped"`, which counts "running"
(a crashed/interrupted run stuck mid-stage) and "failed" as if they were
real successes. That bug was effectively unobservable before
orchestration/run_slate.py's own durable-failed-run fix (a failed run
used to leave zero trace at all -- see test_run_slate_failure_recording.py
-- so there was nothing for this query to miscount); now that a failed
run genuinely leaves `status="failed"`/`"running"` rows behind, this
query must correctly exclude them or a real pipeline failure would
silently suppress that hour's legitimate retry.

Restart-safety itself (this query deriving its answer purely from DB
state, never in-memory counters, so a process restart can never trigger
a redundant run) is a property of every test in this file, not a
separate test -- each one simulates exactly what a fresh post-restart
call would see."""

from __future__ import annotations

from datetime import date

from cassandra.db.models.pipeline import PipelineRun, PipelineRunStage
from cassandra.orchestration.scheduler import _run_slate_success_count_today

SLATE_DATE = date(2026, 8, 5)


def _add_run(db_session, run_id: str, *, publish_status: str) -> None:
    db_session.add(PipelineRun(run_id=run_id, slate_date=SLATE_DATE, status="succeeded"))
    db_session.add(PipelineRunStage(run_id=run_id, stage="PUBLISH", status=publish_status))
    db_session.flush()


def test_zero_when_no_run_exists_for_the_date(db_session):
    assert _run_slate_success_count_today(db_session, SLATE_DATE) == 0


def test_zero_for_a_grade_only_run(db_session):
    # grade_slate_run() always marks PUBLISH "skipped" -- must not be
    # mistaken for a real run_slate() having happened.
    _add_run(db_session, "run_grade_only", publish_status="skipped")
    assert _run_slate_success_count_today(db_session, SLATE_DATE) == 0


def test_one_for_a_single_real_run_slate_publish(db_session):
    _add_run(db_session, "run_real", publish_status="succeeded")
    assert _run_slate_success_count_today(db_session, SLATE_DATE) == 1


def test_counts_multiple_real_runs_on_the_same_date(db_session):
    # The multi-run-per-day cadence needs an actual count, not just a
    # yes/no flag, so should_trigger_run can tell "1 of 3 configured
    # hours done" from "3 of 3 done."
    _add_run(db_session, "run_morning", publish_status="succeeded")
    _add_run(db_session, "run_midday", publish_status="succeeded")
    assert _run_slate_success_count_today(db_session, SLATE_DATE) == 2


def test_zero_for_a_different_slate_date(db_session):
    db_session.add(PipelineRun(run_id="run_other_date", slate_date=date(2026, 8, 4), status="succeeded"))
    db_session.add(PipelineRunStage(run_id="run_other_date", stage="PUBLISH", status="succeeded"))
    db_session.flush()
    assert _run_slate_success_count_today(db_session, SLATE_DATE) == 0


def test_zero_for_a_failed_publish_stage(db_session):
    # A failed run_slate() (orchestration/run_slate.py's _record_failed_run)
    # leaves a durable PipelineRunStage(stage="PUBLISH", status="failed")
    # row behind. It must not be mistaken for a real success, or the
    # scheduler would silently skip that hour's legitimate retry.
    _add_run(db_session, "run_failed", publish_status="failed")
    assert _run_slate_success_count_today(db_session, SLATE_DATE) == 0


def test_zero_for_a_still_running_publish_stage(db_session):
    # A crashed/interrupted run stuck mid-stage (process killed before
    # PUBLISH finished) leaves status="running" behind -- also must not
    # count as a completed success.
    _add_run(db_session, "run_running", publish_status="running")
    assert _run_slate_success_count_today(db_session, SLATE_DATE) == 0


def test_zero_when_publish_succeeded_but_the_run_itself_is_marked_failed(db_session):
    # Both PipelineRun.status and PipelineRunStage(stage="PUBLISH").status
    # must independently be "succeeded" -- a run whose overall status was
    # recorded as failed (e.g. a later stage errored after PUBLISH somehow
    # still marked succeeded) must not be counted just because the PUBLISH
    # stage row alone says succeeded.
    db_session.add(PipelineRun(run_id="run_mismatched", slate_date=SLATE_DATE, status="failed"))
    db_session.add(PipelineRunStage(run_id="run_mismatched", stage="PUBLISH", status="succeeded"))
    db_session.flush()
    assert _run_slate_success_count_today(db_session, SLATE_DATE) == 0


def test_real_success_still_counted_alongside_a_failed_and_a_running_run(db_session):
    # Mixed realistic state: one genuine success plus a failed retry
    # attempt and a still-in-flight run for the same date -- only the
    # real success should be counted.
    _add_run(db_session, "run_real", publish_status="succeeded")
    _add_run(db_session, "run_failed", publish_status="failed")
    _add_run(db_session, "run_running", publish_status="running")
    assert _run_slate_success_count_today(db_session, SLATE_DATE) == 1
