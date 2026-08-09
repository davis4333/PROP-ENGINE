"""Periodic, human-gated model retraining -- the "self-learning loop":
backfills recently-completed games, rebuilds the training dataset, runs a
time-ordered walk-forward out-of-sample comparison against the permanent
baseline AND (whenever one exists) the model Cassandra is CURRENTLY
serving live predictions with, and -- only if the challenger genuinely
beats the baseline on that held-out comparison -- fits and registers a
new CANDIDATE for a human to review and promote (or ignore/reject) by
hand via `cassandra promote-model`/the Admin page. The active-model
comparison is always computed and surfaced (on the artifact's
`training_metrics` and in the audit-event payload) whenever something is
ACTIVE, but registration itself still only requires beating the naive
baseline -- the same deliberately loose bar as before (see
MIN_FOLDS_TO_REGISTER's docstring) -- so a human reviewing candidates
sees "does this beat what's live right now" as real, visible evidence
rather than the registration gate silently hiding a candidate that beat
baseline but lost to the active model.

NEVER promotes anything on its own: this module only ever calls
register_as_candidate() (via train_final_poisson_model(register=True)),
never promote_to_active() -- see registry/service.py's module docstring
for why nothing in this codebase can reach ACTIVE without an explicit
human-supplied --operator action. A run that finds the challenger is NOT
better than the baseline still records the attempt (so cadence gating
below is honest) but registers nothing -- no junk CANDIDATE spam.

Mirrors orchestration/scheduler.py's pattern (pure gating function +
DB-derived restart-safety cadence + best-effort catch-and-log tick +
Postgres advisory lock against concurrent processes) but runs on its own
separate background thread and its own advisory lock key, since a
retrain attempt (backfill + dataset build + walk-forward fit -- possibly
minutes, not seconds) is far heavier/slower than a daily run_slate()/
grade_slate_run() tick and must never delay those. Cadence is derived
from the latest "retrain_attempted" audit_events row (not in-memory
state), so a process restart just re-derives it from the database,
exactly like scheduler.py's run_slate() cadence does.

The numpy-dependent pieces (historical.walk_forward,
historical.train_final_model) are imported lazily inside the tick
function, not at module load time -- this module itself must stay
importable (and its disabled-by-default background thread startable) in
any environment, even one that hasn't installed the `training` extra;
only actually running a tick requires it.
"""

from __future__ import annotations

import gzip
import json as json_module
import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from cassandra.config import settings
from cassandra.db.models.audit import AuditEvent
from cassandra.db.session import engine, session_scope
from cassandra.historical.backfill import BackfillConfig, run_backfill
from cassandra.registry.service import resolve_active_model

logger = logging.getLogger(__name__)

RETRAINING_SCHEDULER_VERSION = "retraining-scheduler-0.1.0"

RETRAIN_ATTEMPTED_EVENT_TYPE = "retrain_attempted"

# A different, fixed advisory-lock key from scheduler.py's
# _SCHEDULER_ADVISORY_LOCK_KEY -- deliberately independent locks so a slow
# retrain tick can never block (or be blocked by) the daily run_slate()/
# grade_slate_run() tick.
_RETRAIN_ADVISORY_LOCK_KEY = 727_364_502

# Minimum improvement to bother registering a CANDIDATE at all -- the
# challenger's aggregate walk-forward MAE must be strictly lower than the
# baseline's. A tie or a regression still gets a durable audit_events
# record (so cadence gating stays honest) but no artifact/registry row.
# Deliberately a bare "beats it at all" bar, not some larger margin --
# picking a real minimum-improvement threshold is a product decision this
# build doesn't guess at (same posture as decision_edge_threshold and
# publication_freeze_minutes_before_first_pitch); a human still reviews
# every registered candidate before promotion, so a marginal improvement
# surfaces for review rather than being hidden, but never gets promoted
# automatically regardless of margin.
MIN_FOLDS_TO_REGISTER = 1


def _local_now() -> datetime:
    return datetime.now(UTC)


def should_trigger_retrain(now: datetime, last_attempt_at: datetime | None, interval_days: int) -> bool:
    """Pure gating rule, split out for testability (no DB/threads/real
    clock needed) -- mirrors scheduler.py's should_trigger_run(). True
    when there's never been an attempt, or the last one was at least
    `interval_days` ago."""
    if last_attempt_at is None:
        return True
    return now - last_attempt_at >= timedelta(days=interval_days)


def _last_retrain_attempt_at(session: Session) -> datetime | None:
    stmt = (
        select(AuditEvent.created_at)
        .where(AuditEvent.event_type == RETRAIN_ATTEMPTED_EVENT_TYPE)
        .order_by(AuditEvent.created_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def _record_attempt(session: Session, payload: dict) -> None:
    session.add(
        AuditEvent(
            event_type=RETRAIN_ATTEMPTED_EVENT_TYPE,
            entity_type="model_artifact",
            entity_id=payload.get("artifact_id"),
            run_id=None,
            payload=payload,
            actor="retraining_scheduler",
        )
    )


def run_scheduled_retrain(now: datetime, client: httpx.Client) -> None:
    """One retrain attempt: backfill -> build dataset -> walk-forward
    evaluate -> register a CANDIDATE only if it genuinely beats the
    baseline. Catches and logs internally (never raises) so a bad attempt
    can't kill the background thread; always records an audit_events row
    so should_trigger_retrain()'s cadence gating stays accurate even for
    a failed/skipped attempt."""
    try:
        from cassandra.historical.dataset_builder import DEFAULT_OUTPUT_DIR, build_training_dataset
        from cassandra.historical.train_final_model import train_final_poisson_model
        from cassandra.historical.walk_forward import MIN_TRAIN_ROWS, run_walk_forward_validation
    except ImportError:
        logger.exception(
            "retraining_scheduler: the 'training' extra (numpy) is not installed -- "
            "cannot run a retrain attempt"
        )
        with session_scope() as session:
            _record_attempt(session, {"outcome": "error", "detail": "training extra (numpy) not installed"})
        return

    today = now.date()
    backfill_start = today - timedelta(days=settings.retrain_backfill_lookback_days)

    try:
        with session_scope() as session:
            run_backfill(session, client, BackfillConfig(start_date=backfill_start, end_date=today))
    except Exception:
        logger.exception("retraining_scheduler: backfill refresh failed")
        with session_scope() as session:
            _record_attempt(session, {"outcome": "error", "detail": "backfill refresh failed"})
        return

    seasons = list(range(settings.retrain_dataset_start_season, today.year + 1))
    output_dir = Path(DEFAULT_OUTPUT_DIR)
    try:
        with session_scope() as session:
            manifest = build_training_dataset(session, seasons=seasons, output_dir=output_dir)
    except Exception:
        logger.exception("retraining_scheduler: dataset build failed")
        with session_scope() as session:
            _record_attempt(session, {"outcome": "error", "detail": "dataset build failed"})
        return

    if manifest.row_count < MIN_TRAIN_ROWS:
        logger.info(
            "retraining_scheduler: dataset %s has only %d rows (< %d) -- skipping this attempt",
            manifest.dataset_id,
            manifest.row_count,
            MIN_TRAIN_ROWS,
        )
        with session_scope() as session:
            _record_attempt(
                session,
                {
                    "outcome": "skipped_insufficient_rows",
                    "dataset_id": manifest.dataset_id,
                    "row_count": manifest.row_count,
                },
            )
        return

    rows: list[dict] = []
    with gzip.open(manifest.output_path, "rt", encoding="utf-8") as fh:
        for line in fh:
            rows.append(json_module.loads(line))

    with session_scope() as session:
        resolved_active = resolve_active_model(session)
    # None whenever nothing has ever been promoted -- the permanent
    # baseline comparison below is unconditional and still meaningful on
    # its own in that bootstrapping case.
    active_model = resolved_active.model if resolved_active.active_artifact_id is not None else None
    active_model_version = resolved_active.model_version if active_model is not None else None

    try:
        wf_result = run_walk_forward_validation(
            rows,
            dataset_id=manifest.dataset_id,
            active_model=active_model,
            active_model_version=active_model_version,
        )
    except Exception:
        logger.exception("retraining_scheduler: walk-forward validation failed")
        with session_scope() as session:
            _record_attempt(
                session,
                {
                    "outcome": "error",
                    "detail": "walk-forward validation failed",
                    "dataset_id": manifest.dataset_id,
                },
            )
        return

    beats_baseline = (
        wf_result.n_folds >= MIN_FOLDS_TO_REGISTER
        and wf_result.aggregate_challenger_mae < wf_result.aggregate_baseline_mae
    )
    # None when nothing has ever been promoted (no active model to
    # compare against) -- deliberately not folded into the registration
    # gate below (that stays "beats the naive baseline," the existing,
    # deliberately loose bar a human still reviews every candidate
    # against), but always computed and surfaced so a human reviewing a
    # pending candidate can see immediately whether it would actually be
    # an upgrade over what Cassandra is using right now, not just an
    # upgrade over the permanent formula.
    beats_active_model = (
        wf_result.aggregate_active_mae is not None
        and wf_result.aggregate_challenger_mae < wf_result.aggregate_active_mae
    )
    attempt_payload = {
        "dataset_id": manifest.dataset_id,
        "row_count": manifest.row_count,
        "walk_forward_n_folds": wf_result.n_folds,
        "walk_forward_n_folds_skipped_insufficient_train_data": (
            wf_result.n_folds_skipped_insufficient_train_data
        ),
        "walk_forward_aggregate_baseline_mae": wf_result.aggregate_baseline_mae,
        "walk_forward_aggregate_challenger_mae": wf_result.aggregate_challenger_mae,
        "beats_baseline": beats_baseline,
        "active_model_version": active_model_version,
        "walk_forward_aggregate_active_mae": wf_result.aggregate_active_mae,
        "beats_active_model": beats_active_model if active_model is not None else None,
    }

    if not beats_baseline:
        logger.info(
            "retraining_scheduler: challenger (mae=%.4f) did not beat baseline (mae=%.4f) on dataset %s "
            "-- not registering a candidate",
            wf_result.aggregate_challenger_mae,
            wf_result.aggregate_baseline_mae,
            manifest.dataset_id,
        )
        attempt_payload["outcome"] = "no_improvement"
        with session_scope() as session:
            _record_attempt(session, attempt_payload)
        return

    active_note = (
        (
            f" Also {'beats' if beats_active_model else 'does NOT beat'} the current ACTIVE model "
            f"({active_model_version}, mae={wf_result.aggregate_active_mae:.4f})."
        )
        if active_model is not None
        else " No model is currently ACTIVE (nothing has been promoted yet), so there is nothing to "
        "compare against beyond the permanent baseline above."
    )
    try:
        result = train_final_poisson_model(
            manifest=manifest,
            rows=rows,
            operator="auto-retrain-scheduler",
            output_dir=output_dir,
            register=True,
            notes=(
                f"Automatic retraining scheduler: walk-forward challenger MAE "
                f"{wf_result.aggregate_challenger_mae:.4f} beat baseline "
                f"{wf_result.aggregate_baseline_mae:.4f} across {wf_result.n_folds} folds."
                f"{active_note} Not promoted automatically -- awaiting human review."
            ),
            walk_forward_metrics={
                "walk_forward_aggregate_baseline_mae": wf_result.aggregate_baseline_mae,
                "walk_forward_aggregate_challenger_mae": wf_result.aggregate_challenger_mae,
                "walk_forward_n_folds": wf_result.n_folds,
                "walk_forward_dataset_id": manifest.dataset_id,
                "walk_forward_active_model_version": active_model_version,
                "walk_forward_aggregate_active_mae": wf_result.aggregate_active_mae,
                "walk_forward_beats_active_model": beats_active_model if active_model is not None else None,
            },
        )
    except Exception:
        logger.exception("retraining_scheduler: train_final_poisson_model failed")
        attempt_payload["outcome"] = "error"
        attempt_payload["detail"] = "train_final_poisson_model failed"
        with session_scope() as session:
            _record_attempt(session, attempt_payload)
        return

    logger.info(
        "retraining_scheduler: registered candidate artifact_id=%s fitted_model_version=%s "
        "-- awaiting human review (cassandra promote-model / rollback-model)",
        result.artifact_id,
        result.fitted_model_version,
    )
    attempt_payload["outcome"] = "candidate_registered"
    attempt_payload["artifact_id"] = result.artifact_id
    attempt_payload["fitted_model_version"] = result.fitted_model_version
    with session_scope() as session:
        _record_attempt(session, attempt_payload)


def _run_scheduled_retrain_locked(now: datetime, client: httpx.Client) -> None:
    """Non-blocking Postgres advisory lock, same reasoning as scheduler.py's
    _run_scheduled_tasks_locked() -- if more than one process somehow runs
    against the same database at once, at most one actually does a given
    tick's (heavy, slow) work."""
    with engine.connect() as conn:
        acquired = conn.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": _RETRAIN_ADVISORY_LOCK_KEY}
        ).scalar_one()
        if not acquired:
            logger.warning(
                "retraining_scheduler: another process already holds the retrain advisory lock -- "
                "skipping this tick"
            )
            return
        try:
            run_scheduled_retrain(now, client)
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _RETRAIN_ADVISORY_LOCK_KEY})


def _retraining_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        now = _local_now()
        with session_scope() as session:
            last_attempt = _last_retrain_attempt_at(session)
        if should_trigger_retrain(now, last_attempt, settings.retrain_interval_days):
            with httpx.Client(timeout=10.0) as client:
                _run_scheduled_retrain_locked(now, client)
        # Poll much less often than the main scheduler -- a retrain
        # attempt is only ever due at most once every retrain_interval_days,
        # so there's no benefit to checking every scheduler_poll_interval_
        # seconds. Checked hourly, cheap and simple, and still restart-safe
        # via the DB-derived cadence above regardless of exact poll timing.
        stop_event.wait(60 * 60)


def start_background_retraining_scheduler() -> threading.Event:
    """Starts the retraining scheduler as a daemon thread when
    settings.auto_retrain_enabled is set; returns a stop Event the caller
    signals to exit cleanly. Returns an already-set Event with no thread
    started when disabled, matching orchestration/scheduler.py's
    start_background_scheduler() so callers never need an `if enabled:`
    branch of their own."""
    stop_event = threading.Event()
    if not settings.auto_retrain_enabled:
        stop_event.set()
        return stop_event
    thread = threading.Thread(
        target=_retraining_loop, args=(stop_event,), daemon=True, name="cassandra-retraining-scheduler"
    )
    thread.start()
    return stop_event


__all__ = [
    "MIN_FOLDS_TO_REGISTER",
    "RETRAINING_SCHEDULER_VERSION",
    "RETRAIN_ATTEMPTED_EVENT_TYPE",
    "run_scheduled_retrain",
    "should_trigger_retrain",
    "start_background_retraining_scheduler",
]
