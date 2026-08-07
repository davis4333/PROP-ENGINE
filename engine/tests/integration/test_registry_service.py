"""registry/service.py against a real Postgres session (db_session --
rolled back after each test, so nothing here permanently pollutes the
shared database) -- artifact creation, the append-only immutability
grants on model_artifacts/model_registry_events, and registry-event
status derivation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from cassandra.db.models.registry import ModelArtifact, ModelRegistryEvent
from cassandra.registry.service import (
    compute_artifact_checksum,
    create_model_artifact,
    current_status,
    record_registry_event,
    register_as_candidate,
)

_BASE_KWARGS = {
    "model_family": "poisson-regression",
    "model_code_version": "poisson-regression-challenger-0.1.0",
    "coefficients": [0.1, 0.2, 0.3],
    "coefficient_order": ["intercept", "log1p_expected_bf", "recent_k_rate"],
    "preprocessing_rules": {"regularization": {"method": "ridge", "lambda": 1.0}},
    "training_dataset_id": "ds_test123",
    "dataset_builder_version": "training-dataset-builder-0.3.0",
    "availability_policy_version": "v1",
    "feature_set_version": "v1",
    "training_seasons": [2023],
    "training_game_types": ["R"],
    "training_row_count": 500,
    "trained_at": datetime(2026, 8, 5, tzinfo=UTC),
    "dependency_versions": {"numpy": "1.26.0"},
    "training_metrics": {"mae": 1.2, "rmse": 1.5},
    "evaluation_report_ids": ["eval_abc123"],
    "created_by": "tester",
}


def _create(db_session, **overrides):
    kwargs = {**_BASE_KWARGS, **overrides}
    return create_model_artifact(db_session, **kwargs)


def test_create_model_artifact_writes_every_field(db_session):
    artifact = _create(db_session)

    assert artifact.artifact_id.startswith("artifact_")
    assert artifact.fitted_model_version == f"poisson-regression-challenger-0.1.0+{artifact.artifact_id}"
    assert artifact.intercept == 0.1  # coefficients[0], coefficient_order[0] == "intercept"
    assert artifact.model_family == "poisson-regression"
    assert artifact.training_row_count == 500
    assert artifact.created_by == "tester"

    reloaded = db_session.get(ModelArtifact, artifact.artifact_id)
    assert reloaded is not None
    assert reloaded.coefficients == [0.1, 0.2, 0.3]


def test_create_model_artifact_rejects_coefficient_order_not_starting_with_intercept(db_session):
    with pytest.raises(ValueError, match="intercept"):
        _create(db_session, coefficient_order=["log1p_expected_bf", "recent_k_rate", "intercept"])


def test_checksum_is_deterministic_and_ignores_bookkeeping_fields(db_session):
    # Two artifacts fit identically (same family/coefficients/dataset)
    # must get the same checksum even though their artifact_id/
    # trained_at/created_by differ -- the checksum answers "does this
    # predict the same way," not "is this the same row."
    a = _create(db_session, created_by="alice")
    b = _create(db_session, created_by="bob", trained_at=datetime(2026, 8, 6, tzinfo=UTC))
    assert a.artifact_checksum == b.artifact_checksum
    assert a.artifact_id != b.artifact_id


def test_checksum_changes_when_coefficients_differ(db_session):
    a = _create(db_session)
    b = _create(db_session, coefficients=[0.9, 0.2, 0.3])
    assert a.artifact_checksum != b.artifact_checksum


def test_compute_artifact_checksum_matches_a_direct_call(db_session):
    artifact = _create(db_session)
    direct = compute_artifact_checksum(
        model_family=_BASE_KWARGS["model_family"],
        model_code_version=_BASE_KWARGS["model_code_version"],
        coefficients=_BASE_KWARGS["coefficients"],
        coefficient_order=_BASE_KWARGS["coefficient_order"],
        preprocessing_rules=_BASE_KWARGS["preprocessing_rules"],
        training_dataset_id=_BASE_KWARGS["training_dataset_id"],
    )
    assert artifact.artifact_checksum == direct


def test_model_artifacts_update_is_blocked_by_the_immutability_trigger(db_session):
    artifact = _create(db_session)
    db_session.flush()
    with pytest.raises(DBAPIError, match="append-only"):
        db_session.execute(
            text("UPDATE model_artifacts SET notes = 'hacked' WHERE artifact_id = :id"),
            {"id": artifact.artifact_id},
        )


def test_model_artifacts_delete_is_blocked(db_session):
    artifact = _create(db_session)
    db_session.flush()
    with pytest.raises(DBAPIError):
        db_session.execute(
            text("DELETE FROM model_artifacts WHERE artifact_id = :id"), {"id": artifact.artifact_id}
        )


def test_register_as_candidate_creates_a_registered_event_with_no_prior_status(db_session):
    artifact = _create(db_session)
    event = register_as_candidate(db_session, artifact_id=artifact.artifact_id, operator="tyler")

    assert event.event_type == "registered"
    assert event.from_status is None
    assert event.to_status == "CANDIDATE"
    assert event.operator == "tyler"

    reloaded = db_session.get(ModelRegistryEvent, event.event_id)
    assert reloaded is not None
    assert reloaded.artifact_id == artifact.artifact_id


def test_current_status_is_none_before_any_registration(db_session):
    artifact = _create(db_session)
    assert current_status(db_session, artifact.artifact_id) is None


def test_current_status_reflects_the_latest_event(db_session):
    artifact = _create(db_session)
    register_as_candidate(db_session, artifact_id=artifact.artifact_id, operator="tyler")
    assert current_status(db_session, artifact.artifact_id) == "CANDIDATE"


def test_record_registry_event_rejects_an_invalid_to_status(db_session):
    artifact = _create(db_session)
    with pytest.raises(ValueError, match="to_status"):
        record_registry_event(
            db_session,
            artifact_id=artifact.artifact_id,
            event_type="bogus",
            to_status="NOT_A_REAL_STATUS",
            operator="tyler",
        )


def test_model_registry_events_update_is_blocked(db_session):
    artifact = _create(db_session)
    event = register_as_candidate(db_session, artifact_id=artifact.artifact_id, operator="tyler")
    db_session.flush()
    with pytest.raises(DBAPIError, match="append-only"):
        db_session.execute(
            text("UPDATE model_registry_events SET reason = 'hacked' WHERE event_id = :id"),
            {"id": event.event_id},
        )
