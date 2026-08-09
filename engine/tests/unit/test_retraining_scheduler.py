"""orchestration/retraining_scheduler.py's pure gating logic and the
run_scheduled_retrain() decision tree, tested without a real database or
network -- session_scope()/run_backfill() and the lazily-imported
historical.* functions are monkeypatched to fakes, so these exercise only
the scheduler's own decisions (when a retrain is due, whether a
challenger beats the baseline, that it never calls promote_to_active).
The DB-backed cadence query (_last_retrain_attempt_at) is proven
separately against a real Postgres session in
tests/integration/test_retraining_scheduler_reconciliation.py."""

from __future__ import annotations

import gzip
import json
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cassandra.historical.dataset_builder import DatasetManifest
from cassandra.orchestration import retraining_scheduler as rs
from cassandra.registry.service import ResolvedModel


def test_should_trigger_retrain_true_when_never_attempted():
    now = datetime(2026, 8, 5, tzinfo=UTC)
    assert rs.should_trigger_retrain(now, None, interval_days=7) is True


def test_should_trigger_retrain_false_before_interval_elapses():
    now = datetime(2026, 8, 5, tzinfo=UTC)
    last = now - timedelta(days=3)
    assert rs.should_trigger_retrain(now, last, interval_days=7) is False


def test_should_trigger_retrain_true_once_interval_elapses():
    now = datetime(2026, 8, 5, tzinfo=UTC)
    last = now - timedelta(days=7)
    assert rs.should_trigger_retrain(now, last, interval_days=7) is True


def test_should_trigger_retrain_true_well_past_interval():
    now = datetime(2026, 8, 5, tzinfo=UTC)
    last = now - timedelta(days=30)
    assert rs.should_trigger_retrain(now, last, interval_days=7) is True


@contextmanager
def _fake_session_scope():
    yield object()


def _manifest(dataset_id: str, output_path: str, row_count: int) -> DatasetManifest:
    return DatasetManifest(
        dataset_id=dataset_id,
        dataset_version="training-dataset-builder-0.3.0+v1",
        tier="STRICT_LIVE_COMPATIBLE",
        seasons=[2023],
        game_types=["R"],
        availability_policy_version="v1",
        feature_set_version="v1",
        expected_bf_version="v1",
        dataset_builder_version="training-dataset-builder-0.3.0",
        built_at=datetime.now(UTC).isoformat(),
        row_count=row_count,
        output_path=output_path,
        excluded_feature_groups=["lineup", "umpire"],
        coverage_notes={},
    )


def _write_gzip_rows(path, rows: list[dict]) -> str:
    data_path = path / "fake_dataset.jsonl.gz"
    with gzip.open(data_path, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return str(data_path)


@dataclass(frozen=True)
class _FakeWalkForwardResult:
    n_folds: int
    n_folds_skipped_insufficient_train_data: int
    aggregate_baseline_mae: float
    aggregate_challenger_mae: float
    active_model_version: str | None = None
    aggregate_active_mae: float | None = None


def _patch_common(
    monkeypatch, *, backfill_calls, attempts, active_model_version=None, active_artifact_id=None
):
    monkeypatch.setattr(rs, "session_scope", _fake_session_scope)
    monkeypatch.setattr(rs, "run_backfill", lambda session, client, config: backfill_calls.append(config))
    monkeypatch.setattr(rs, "_record_attempt", lambda session, payload: attempts.append(payload))
    # Default: nothing has ever been promoted (the common bootstrapping
    # case) -- individual tests override active_artifact_id/
    # active_model_version to exercise the "compared against the
    # currently ACTIVE model too" path.
    monkeypatch.setattr(
        rs,
        "resolve_active_model",
        lambda session: ResolvedModel(
            model=object(),  # unused here -- run_walk_forward_validation itself is mocked below
            model_version=active_model_version or "k-model-0.1.0",
            active_artifact_id=active_artifact_id,
        ),
    )


def test_run_scheduled_retrain_skips_when_dataset_has_too_few_rows(monkeypatch, tmp_path):
    backfill_calls: list = []
    attempts: list[dict] = []
    _patch_common(monkeypatch, backfill_calls=backfill_calls, attempts=attempts)

    manifest = _manifest("ds_tiny", str(tmp_path / "unused.jsonl.gz"), row_count=5)
    monkeypatch.setattr(
        "cassandra.historical.dataset_builder.build_training_dataset",
        lambda session, *, seasons, output_dir: manifest,
    )
    train_calls: list = []
    monkeypatch.setattr(
        "cassandra.historical.train_final_model.train_final_poisson_model",
        lambda **kwargs: train_calls.append(kwargs),
    )

    rs.run_scheduled_retrain(datetime(2026, 8, 5, tzinfo=UTC), client=object())

    assert len(backfill_calls) == 1
    assert train_calls == []
    assert len(attempts) == 1
    assert attempts[0]["outcome"] == "skipped_insufficient_rows"
    assert attempts[0]["dataset_id"] == "ds_tiny"


def test_run_scheduled_retrain_does_not_register_when_challenger_does_not_beat_baseline(
    monkeypatch, tmp_path
):
    backfill_calls: list = []
    attempts: list[dict] = []
    _patch_common(monkeypatch, backfill_calls=backfill_calls, attempts=attempts)

    data_path = _write_gzip_rows(tmp_path, [{"x": i} for i in range(250)])
    manifest = _manifest("ds_worse", data_path, row_count=250)
    monkeypatch.setattr(
        "cassandra.historical.dataset_builder.build_training_dataset",
        lambda session, *, seasons, output_dir: manifest,
    )
    monkeypatch.setattr(
        "cassandra.historical.walk_forward.run_walk_forward_validation",
        lambda rows, *, dataset_id, **_: _FakeWalkForwardResult(
            n_folds=3,
            n_folds_skipped_insufficient_train_data=0,
            aggregate_baseline_mae=1.0,
            aggregate_challenger_mae=1.2,  # worse than baseline
        ),
    )
    train_calls: list = []
    monkeypatch.setattr(
        "cassandra.historical.train_final_model.train_final_poisson_model",
        lambda **kwargs: train_calls.append(kwargs),
    )

    rs.run_scheduled_retrain(datetime(2026, 8, 5, tzinfo=UTC), client=object())

    assert train_calls == []
    assert len(attempts) == 1
    assert attempts[0]["outcome"] == "no_improvement"
    assert attempts[0]["beats_baseline"] is False


def test_run_scheduled_retrain_registers_a_candidate_when_challenger_beats_baseline(monkeypatch, tmp_path):
    backfill_calls: list = []
    attempts: list[dict] = []
    _patch_common(monkeypatch, backfill_calls=backfill_calls, attempts=attempts)

    data_path = _write_gzip_rows(tmp_path, [{"x": i} for i in range(250)])
    manifest = _manifest("ds_better", data_path, row_count=250)
    monkeypatch.setattr(
        "cassandra.historical.dataset_builder.build_training_dataset",
        lambda session, *, seasons, output_dir: manifest,
    )
    monkeypatch.setattr(
        "cassandra.historical.walk_forward.run_walk_forward_validation",
        lambda rows, *, dataset_id, **_: _FakeWalkForwardResult(
            n_folds=3,
            n_folds_skipped_insufficient_train_data=0,
            aggregate_baseline_mae=1.5,
            aggregate_challenger_mae=1.1,  # beats baseline
        ),
    )

    @dataclass(frozen=True)
    class _FakeTrainResult:
        artifact_id: str = "artifact_fake123"
        fitted_model_version: str = "poisson-regression-challenger-0.1.0+artifact_fake123"

    train_calls: list = []

    def fake_train(**kwargs):
        train_calls.append(kwargs)
        return _FakeTrainResult()

    monkeypatch.setattr("cassandra.historical.train_final_model.train_final_poisson_model", fake_train)

    rs.run_scheduled_retrain(datetime(2026, 8, 5, tzinfo=UTC), client=object())

    assert len(train_calls) == 1
    call = train_calls[0]
    assert call["register"] is True
    assert call["operator"] == "auto-retrain-scheduler"
    assert call["walk_forward_metrics"] == {
        "walk_forward_aggregate_baseline_mae": 1.5,
        "walk_forward_aggregate_challenger_mae": 1.1,
        "walk_forward_n_folds": 3,
        "walk_forward_dataset_id": "ds_better",
        "walk_forward_active_model_version": None,
        "walk_forward_aggregate_active_mae": None,
        "walk_forward_beats_active_model": None,
    }
    assert len(attempts) == 1
    assert attempts[0]["outcome"] == "candidate_registered"
    assert attempts[0]["artifact_id"] == "artifact_fake123"
    # No active model was ever promoted in this test -- beats_active_model
    # must be None (unknown/not-applicable), never a false True or False.
    assert attempts[0]["beats_active_model"] is None


def test_run_scheduled_retrain_compares_against_the_current_active_model_when_one_exists(
    monkeypatch, tmp_path
):
    # Regression for a real gap: previously a candidate was only ever
    # compared to the permanent baseline, never to whatever Cassandra is
    # CURRENTLY serving live predictions with -- the actual question a
    # promotion decision needs answered. This proves resolve_active_model()
    # is consulted and its result (a real ACTIVE artifact) is threaded
    # into the walk-forward comparison and the registered artifact's
    # training_metrics.
    backfill_calls: list = []
    attempts: list[dict] = []
    _patch_common(
        monkeypatch,
        backfill_calls=backfill_calls,
        attempts=attempts,
        active_model_version="poisson-regression-challenger-0.1.0+artifact_currently_live",
        active_artifact_id="artifact_currently_live",
    )

    data_path = _write_gzip_rows(tmp_path, [{"x": i} for i in range(250)])
    manifest = _manifest("ds_vs_active", data_path, row_count=250)
    monkeypatch.setattr(
        "cassandra.historical.dataset_builder.build_training_dataset",
        lambda session, *, seasons, output_dir: manifest,
    )

    wf_calls: list = []

    def fake_wf(rows, *, dataset_id, n_folds=5, active_model=None, active_model_version=None):
        wf_calls.append({"active_model": active_model, "active_model_version": active_model_version})
        return _FakeWalkForwardResult(
            n_folds=3,
            n_folds_skipped_insufficient_train_data=0,
            aggregate_baseline_mae=1.5,
            aggregate_challenger_mae=1.1,  # beats baseline
            active_model_version=active_model_version,
            aggregate_active_mae=1.3,  # challenger (1.1) also beats this
        )

    monkeypatch.setattr("cassandra.historical.walk_forward.run_walk_forward_validation", fake_wf)

    @dataclass(frozen=True)
    class _FakeTrainResult:
        artifact_id: str = "artifact_fake456"
        fitted_model_version: str = "poisson-regression-challenger-0.1.0+artifact_fake456"

    train_calls: list = []

    def fake_train(**kwargs):
        train_calls.append(kwargs)
        return _FakeTrainResult()

    monkeypatch.setattr("cassandra.historical.train_final_model.train_final_poisson_model", fake_train)

    rs.run_scheduled_retrain(datetime(2026, 8, 5, tzinfo=UTC), client=object())

    # resolve_active_model()'s result genuinely reached
    # run_walk_forward_validation() as a real model + version, not
    # silently dropped.
    assert len(wf_calls) == 1
    assert wf_calls[0]["active_model_version"] == (
        "poisson-regression-challenger-0.1.0+artifact_currently_live"
    )
    assert wf_calls[0]["active_model"] is not None

    assert len(train_calls) == 1
    metrics = train_calls[0]["walk_forward_metrics"]
    assert metrics["walk_forward_active_model_version"] == (
        "poisson-regression-challenger-0.1.0+artifact_currently_live"
    )
    assert metrics["walk_forward_aggregate_active_mae"] == 1.3
    assert metrics["walk_forward_beats_active_model"] is True

    assert attempts[0]["beats_active_model"] is True
    assert attempts[0]["walk_forward_aggregate_active_mae"] == 1.3
    # The human reviewing this candidate must see the active-model
    # comparison in plain language, not just buried in a metrics dict.
    assert "ACTIVE model" in train_calls[0]["notes"]
    assert "beats" in train_calls[0]["notes"]


def test_run_scheduled_retrain_still_registers_when_it_beats_baseline_but_not_the_active_model(
    monkeypatch, tmp_path
):
    # The registration bar stays "beats the naive baseline" (deliberately
    # loose, unchanged) -- but a candidate that loses to the active model
    # must still be registered (a human should see it and decide, not
    # have it silently hidden), with that fact clearly visible rather
    # than papered over.
    backfill_calls: list = []
    attempts: list[dict] = []
    _patch_common(
        monkeypatch,
        backfill_calls=backfill_calls,
        attempts=attempts,
        active_model_version="poisson-regression-challenger-0.1.0+artifact_currently_live",
        active_artifact_id="artifact_currently_live",
    )

    data_path = _write_gzip_rows(tmp_path, [{"x": i} for i in range(250)])
    manifest = _manifest("ds_loses_to_active", data_path, row_count=250)
    monkeypatch.setattr(
        "cassandra.historical.dataset_builder.build_training_dataset",
        lambda session, *, seasons, output_dir: manifest,
    )
    monkeypatch.setattr(
        "cassandra.historical.walk_forward.run_walk_forward_validation",
        lambda rows, *, dataset_id, n_folds=5, active_model=None, active_model_version=None: (
            _FakeWalkForwardResult(
                n_folds=3,
                n_folds_skipped_insufficient_train_data=0,
                aggregate_baseline_mae=1.5,
                aggregate_challenger_mae=1.1,  # beats baseline (1.5)...
                active_model_version=active_model_version,
                aggregate_active_mae=0.9,  # ...but loses to the active model (0.9)
            )
        ),
    )

    @dataclass(frozen=True)
    class _FakeTrainResult:
        artifact_id: str = "artifact_fake789"
        fitted_model_version: str = "poisson-regression-challenger-0.1.0+artifact_fake789"

    train_calls: list = []
    monkeypatch.setattr(
        "cassandra.historical.train_final_model.train_final_poisson_model",
        lambda **kwargs: (train_calls.append(kwargs), _FakeTrainResult())[1],
    )

    rs.run_scheduled_retrain(datetime(2026, 8, 5, tzinfo=UTC), client=object())

    # Still registered -- beating baseline remains the registration bar.
    assert len(train_calls) == 1
    assert train_calls[0]["walk_forward_metrics"]["walk_forward_beats_active_model"] is False
    assert "does NOT beat" in train_calls[0]["notes"]
    assert attempts[0]["outcome"] == "candidate_registered"
    assert attempts[0]["beats_active_model"] is False


def test_retraining_scheduler_module_never_references_promote_to_active():
    """A real AST-level guarantee (not just "this test's fakes never call
    it"): the module's source never even names promote_to_active/
    rollback_active anywhere -- this scheduler can only ever reach
    register_as_candidate() (via train_final_poisson_model(register=True)),
    matching the module's own docstring claim that nothing here can
    promote a model on its own."""
    import ast
    import inspect

    from cassandra.orchestration import retraining_scheduler as rs_module

    source = inspect.getsource(rs_module)
    names = {node.id for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Attribute)
    }
    assert "promote_to_active" not in names
    assert "rollback_active" not in names


def test_run_scheduled_retrain_records_an_attempt_when_backfill_fails(monkeypatch, tmp_path):
    attempts: list[dict] = []
    monkeypatch.setattr(rs, "session_scope", _fake_session_scope)
    monkeypatch.setattr(rs, "_record_attempt", lambda session, payload: attempts.append(payload))

    def raising_backfill(session, client, config):
        raise RuntimeError("simulated MLB API outage")

    monkeypatch.setattr(rs, "run_backfill", raising_backfill)

    rs.run_scheduled_retrain(datetime(2026, 8, 5, tzinfo=UTC), client=object())

    assert len(attempts) == 1
    assert attempts[0]["outcome"] == "error"


class _RecordingStopEvent:
    def __init__(self) -> None:
        self.wait_calls: list[float] = []
        self._set = False

    def is_set(self) -> bool:
        return self._set

    def wait(self, timeout: float) -> None:
        self.wait_calls.append(timeout)
        self._set = True


def test_start_background_retraining_scheduler_is_a_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(rs.settings, "auto_retrain_enabled", False)
    stop_event = rs.start_background_retraining_scheduler()
    assert stop_event.is_set()


def test_start_background_retraining_scheduler_starts_a_daemon_thread_when_enabled(monkeypatch):
    monkeypatch.setattr(rs.settings, "auto_retrain_enabled", True)
    loop_started = threading.Event()

    def fake_loop(stop_event: threading.Event) -> None:
        loop_started.set()
        stop_event.wait()

    monkeypatch.setattr(rs, "_retraining_loop", fake_loop)
    stop_event = rs.start_background_retraining_scheduler()
    try:
        assert loop_started.wait(timeout=2), "background thread never started"
    finally:
        stop_event.set()
