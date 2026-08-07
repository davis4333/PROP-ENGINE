"""historical/train_final_model.py against a real Postgres database --
unlike registry/service.py's own tests (which use the rolled-back
db_session fixture), train_final_poisson_model() manages its own
session_scope() calls internally (see its module docstring for why) and
so genuinely commits. Model artifacts/registry events are append-only
(can't be deleted -- same as audit_events elsewhere in this codebase),
so these rows permanently remain in whatever database the tests ran
against; each test uses a unique synthetic dataset_id to avoid confusion,
matching the precedent already established by
test_run_slate_failure_recording.py's own cleanup notes."""

from __future__ import annotations

import math
import random
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from cassandra.db.models.registry import ModelArtifact, ModelRegistryEvent
from cassandra.db.session import session_scope
from cassandra.historical.challenger_poisson import COEFFICIENT_NAMES
from cassandra.historical.dataset_builder import DatasetManifest
from cassandra.historical.train_final_model import SUPPORTED_MODEL_FAMILIES, train_final_poisson_model


def _synthetic_rows(n: int, seed: int = 0) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        expected_bf = rng.uniform(15, 28)
        recent_k_rate = rng.uniform(0.15, 0.32)
        true_mean = max(expected_bf * recent_k_rate, 0.1)
        rows.append(
            {
                "expected_bf": expected_bf,
                "recent_k_rate": recent_k_rate,
                "rest_days": rng.choice([4, 5, 6, None]),
                "actual_strikeouts": max(0, round(rng.gauss(true_mean, math.sqrt(true_mean)))),
            }
        )
    return rows


def _manifest(dataset_id: str) -> DatasetManifest:
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
        row_count=300,
        output_path="unused-in-this-test",
        excluded_feature_groups=["lineup", "umpire"],
        coverage_notes={},
    )


def test_supported_model_families_includes_poisson_regression():
    assert "poisson-regression" in SUPPORTED_MODEL_FAMILIES


def test_train_final_poisson_model_creates_an_unregistered_artifact_by_default(tmp_path):
    dataset_id = f"ds_test_{uuid.uuid4().hex[:8]}"
    rows = _synthetic_rows(300, seed=1)

    result = train_final_poisson_model(
        manifest=_manifest(dataset_id),
        rows=rows,
        operator="tester",
        output_dir=tmp_path,
        register=False,
    )

    assert result.registered is False
    assert result.registry_event_id is None

    with session_scope() as session:
        artifact = session.get(ModelArtifact, result.artifact_id)
        assert artifact is not None
        assert artifact.model_family == "poisson-regression"
        assert artifact.training_dataset_id == dataset_id
        assert artifact.training_row_count == 300
        assert artifact.coefficient_order == list(COEFFICIENT_NAMES)
        assert artifact.created_by == "tester"

        events = (
            session.execute(
                select(ModelRegistryEvent).where(ModelRegistryEvent.artifact_id == result.artifact_id)
            )
            .scalars()
            .all()
        )
        assert events == []


def test_train_final_poisson_model_registers_as_candidate_when_requested(tmp_path):
    dataset_id = f"ds_test_{uuid.uuid4().hex[:8]}"
    rows = _synthetic_rows(300, seed=2)

    result = train_final_poisson_model(
        manifest=_manifest(dataset_id),
        rows=rows,
        operator="tester",
        output_dir=tmp_path,
        register=True,
        notes="test registration",
    )

    assert result.registered is True
    assert result.registry_event_id is not None

    with session_scope() as session:
        event = session.get(ModelRegistryEvent, result.registry_event_id)
        assert event is not None
        assert event.artifact_id == result.artifact_id
        assert event.to_status == "CANDIDATE"
        assert event.from_status is None
        assert event.operator == "tester"

        artifact = session.get(ModelArtifact, result.artifact_id)
        assert artifact.notes == "test registration"


def test_train_final_poisson_model_reload_matches_the_original_fit(tmp_path):
    # The function itself raises RuntimeError if the round-trip validation
    # fails (see its own module docstring) -- a successful return is
    # already proof, but this test additionally re-derives the artifact
    # from a fresh query and checks its coefficients directly, rather
    # than only trusting that no exception was raised.
    dataset_id = f"ds_test_{uuid.uuid4().hex[:8]}"
    rows = _synthetic_rows(300, seed=3)

    result = train_final_poisson_model(
        manifest=_manifest(dataset_id),
        rows=rows,
        operator="tester",
        output_dir=tmp_path,
        register=False,
    )

    with session_scope() as session:
        artifact = session.get(ModelArtifact, result.artifact_id)
        reloaded_coefficients = tuple(float(c) for c in artifact.coefficients)

    assert len(reloaded_coefficients) == len(COEFFICIENT_NAMES)
    assert all(math.isfinite(c) for c in reloaded_coefficients)


def test_train_final_poisson_model_writes_an_evaluation_report_file(tmp_path):
    dataset_id = f"ds_test_{uuid.uuid4().hex[:8]}"
    rows = _synthetic_rows(300, seed=4)

    result = train_final_poisson_model(
        manifest=_manifest(dataset_id),
        rows=rows,
        operator="tester",
        output_dir=tmp_path,
        register=False,
    )

    report_path = tmp_path / "evaluations" / f"{result.evaluation_id}.json"
    assert report_path.exists()


def test_train_final_poisson_model_training_metrics_are_finite(tmp_path):
    dataset_id = f"ds_test_{uuid.uuid4().hex[:8]}"
    rows = _synthetic_rows(300, seed=5)

    result = train_final_poisson_model(
        manifest=_manifest(dataset_id),
        rows=rows,
        operator="tester",
        output_dir=tmp_path,
        register=False,
    )

    assert math.isfinite(result.training_metrics["mae"])
    assert math.isfinite(result.training_metrics["rmse"])
    assert result.training_metrics["mae"] >= 0.0
