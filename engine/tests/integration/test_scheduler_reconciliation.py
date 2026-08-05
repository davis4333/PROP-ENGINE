"""orchestration/scheduler.py's _run_slate_already_succeeded_today()
against a real Postgres session -- proves the actual SQL correctly tells
a real run_slate() PipelineRun apart from a grade_slate_run()-only one
for the same slate_date (both write a PipelineRun row; only run_slate()
ever marks PUBLISH as anything other than "skipped")."""

from __future__ import annotations

from datetime import date

from cassandra.db.models.pipeline import PipelineRun, PipelineRunStage
from cassandra.orchestration.scheduler import _run_slate_already_succeeded_today

SLATE_DATE = date(2026, 8, 5)


def _add_run(db_session, run_id: str, *, publish_status: str) -> None:
    db_session.add(PipelineRun(run_id=run_id, slate_date=SLATE_DATE, status="succeeded"))
    db_session.add(PipelineRunStage(run_id=run_id, stage="PUBLISH", status=publish_status))
    db_session.flush()


def test_false_when_no_run_exists_for_the_date(db_session):
    assert _run_slate_already_succeeded_today(db_session, SLATE_DATE) is False


def test_false_for_a_grade_only_run(db_session):
    # grade_slate_run() always marks PUBLISH "skipped" -- must not be
    # mistaken for a real run_slate() having happened.
    _add_run(db_session, "run_grade_only", publish_status="skipped")
    assert _run_slate_already_succeeded_today(db_session, SLATE_DATE) is False


def test_true_for_a_real_run_slate_publish(db_session):
    _add_run(db_session, "run_real", publish_status="succeeded")
    assert _run_slate_already_succeeded_today(db_session, SLATE_DATE) is True


def test_false_for_a_different_slate_date(db_session):
    db_session.add(PipelineRun(run_id="run_other_date", slate_date=date(2026, 8, 4), status="succeeded"))
    db_session.add(PipelineRunStage(run_id="run_other_date", stage="PUBLISH", status="succeeded"))
    db_session.flush()
    assert _run_slate_already_succeeded_today(db_session, SLATE_DATE) is False
