"""registry/service.py against a real Postgres session (db_session --
rolled back after each test, so nothing here permanently pollutes the
shared database) -- artifact creation, the append-only immutability
grants on model_artifacts/model_registry_events, and registry-event
status derivation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, MultipleResultsFound

from cassandra.db.models.registry import ModelArtifact, ModelRegistryEvent
from cassandra.models.baseline import MODEL_VERSION as BASELINE_MODEL_VERSION
from cassandra.models.baseline import BaselinePoissonModel
from cassandra.models.negative_binomial_regression import NegativeBinomialRegressionModel
from cassandra.models.poisson_regression import PoissonRegressionModel
from cassandra.registry.service import (
    active_artifact,
    compute_artifact_checksum,
    create_model_artifact,
    current_status,
    promote_to_active,
    record_registry_event,
    register_as_candidate,
    resolve_active_model,
    rollback_active,
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
    # walk_forward_* keys required by promote_to_active() (see
    # REQUIRED_WALK_FORWARD_METRIC_KEYS) -- included here so every
    # existing promotion/rollback test doesn't need its own override;
    # test_promote_to_active_refuses_an_artifact_missing_walk_forward_
    # metrics below is the dedicated regression test for the gate itself.
    "training_metrics": {
        "mae": 1.2,
        "rmse": 1.5,
        "walk_forward_aggregate_baseline_mae": 1.8,
        "walk_forward_aggregate_challenger_mae": 1.3,
    },
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


def test_active_artifact_is_none_when_nothing_has_ever_been_registered(db_session):
    _create(db_session)  # exists, but never registered/activated
    assert active_artifact(db_session) is None


def test_active_artifact_is_none_when_only_candidate(db_session):
    artifact = _create(db_session)
    register_as_candidate(db_session, artifact_id=artifact.artifact_id, operator="tyler")
    assert active_artifact(db_session) is None


def test_active_artifact_returns_the_activated_one(db_session):
    artifact = _create(db_session)
    record_registry_event(
        db_session,
        artifact_id=artifact.artifact_id,
        event_type="activated",
        to_status="ACTIVE",
        operator="tyler",
        from_status="CANDIDATE",
    )
    found = active_artifact(db_session)
    assert found is not None
    assert found.artifact_id == artifact.artifact_id


def test_active_artifact_ignores_a_retired_one(db_session):
    artifact = _create(db_session)
    record_registry_event(
        db_session,
        artifact_id=artifact.artifact_id,
        event_type="activated",
        to_status="ACTIVE",
        operator="tyler",
        from_status="CANDIDATE",
    )
    record_registry_event(
        db_session,
        artifact_id=artifact.artifact_id,
        event_type="retired",
        to_status="RETIRED",
        operator="tyler",
        from_status="ACTIVE",
    )
    assert active_artifact(db_session) is None


def test_active_artifact_raises_if_two_artifacts_are_somehow_both_active(db_session):
    # A real data-integrity violation (should be structurally impossible
    # once promote_to_active() always atomically retires the previous
    # ACTIVE artifact in the same transaction) -- active_artifact() must
    # surface this loudly, never silently guess which one "really" counts.
    a = _create(db_session, model_code_version="v-a")
    b = _create(db_session, model_code_version="v-b")
    for artifact in (a, b):
        record_registry_event(
            db_session,
            artifact_id=artifact.artifact_id,
            event_type="activated",
            to_status="ACTIVE",
            operator="tyler",
            from_status="CANDIDATE",
        )
    with pytest.raises(MultipleResultsFound):
        active_artifact(db_session)


def test_resolve_active_model_falls_back_to_baseline_when_nothing_is_active(db_session):
    resolved = resolve_active_model(db_session)
    assert isinstance(resolved.model, BaselinePoissonModel)
    assert resolved.model_version == BASELINE_MODEL_VERSION
    assert resolved.active_artifact_id is None


def test_resolve_active_model_returns_the_active_poisson_artifact(db_session):
    artifact = _create(db_session, coefficients=[0.5, 0.1, 2.0, -0.02, 0.0])
    record_registry_event(
        db_session,
        artifact_id=artifact.artifact_id,
        event_type="activated",
        to_status="ACTIVE",
        operator="tyler",
        from_status="CANDIDATE",
    )
    resolved = resolve_active_model(db_session)
    assert isinstance(resolved.model, PoissonRegressionModel)
    assert resolved.model.coefficients == (0.5, 0.1, 2.0, -0.02, 0.0)
    assert resolved.model_version == artifact.fitted_model_version
    assert resolved.active_artifact_id == artifact.artifact_id


def test_resolve_active_model_returns_the_active_negative_binomial_artifact(db_session):
    artifact = _create(
        db_session,
        model_family="negative-binomial-regression",
        model_code_version="negative-binomial-regression-challenger-0.1.0",
        coefficients=[0.5, 0.1, 2.0, -0.02, 0.0],
        # dispersion lives in preprocessing_rules, not coefficients (see
        # registry/service.py's resolve_active_model() and train_final_
        # model.py's _negative_binomial_preprocessing_rules()).
        preprocessing_rules={"dispersion": 0.025},
    )
    record_registry_event(
        db_session,
        artifact_id=artifact.artifact_id,
        event_type="activated",
        to_status="ACTIVE",
        operator="tyler",
        from_status="CANDIDATE",
    )
    resolved = resolve_active_model(db_session)
    assert isinstance(resolved.model, NegativeBinomialRegressionModel)
    assert resolved.model.coefficients == (0.5, 0.1, 2.0, -0.02, 0.0)
    assert resolved.model.dispersion == 0.025
    assert resolved.model_version == artifact.fitted_model_version
    assert resolved.active_artifact_id == artifact.artifact_id


def test_resolve_active_model_raises_for_an_unsupported_family(db_session):
    artifact = _create(db_session, model_family="some-future-family")
    record_registry_event(
        db_session,
        artifact_id=artifact.artifact_id,
        event_type="activated",
        to_status="ACTIVE",
        operator="tyler",
        from_status="CANDIDATE",
    )
    with pytest.raises(ValueError, match="some-future-family"):
        resolve_active_model(db_session)


def test_promote_to_active_requires_registration_first(db_session):
    artifact = _create(db_session)  # never registered -- status is None
    with pytest.raises(ValueError, match="CANDIDATE"):
        promote_to_active(db_session, artifact_id=artifact.artifact_id, operator="tyler")


def test_promote_to_active_activates_a_candidate(db_session):
    artifact = _create(db_session)
    register_as_candidate(db_session, artifact_id=artifact.artifact_id, operator="tyler")

    event = promote_to_active(db_session, artifact_id=artifact.artifact_id, operator="tyler", reason="v1")

    assert event.to_status == "ACTIVE"
    assert event.from_status == "CANDIDATE"
    assert current_status(db_session, artifact.artifact_id) == "ACTIVE"
    resolved = active_artifact(db_session)
    assert resolved is not None
    assert resolved.artifact_id == artifact.artifact_id


def test_promote_to_active_atomically_retires_the_previous_active_artifact(db_session):
    first = _create(db_session, model_code_version="v-first")
    register_as_candidate(db_session, artifact_id=first.artifact_id, operator="tyler")
    promote_to_active(db_session, artifact_id=first.artifact_id, operator="tyler")

    second = _create(db_session, model_code_version="v-second")
    register_as_candidate(db_session, artifact_id=second.artifact_id, operator="tyler")
    promote_to_active(db_session, artifact_id=second.artifact_id, operator="tyler")

    assert current_status(db_session, first.artifact_id) == "RETIRED"
    assert current_status(db_session, second.artifact_id) == "ACTIVE"
    # Never two ACTIVE at once, even mid-promotion within the same call --
    # active_artifact() would raise MultipleResultsFound if this broke.
    resolved = active_artifact(db_session)
    assert resolved is not None
    assert resolved.artifact_id == second.artifact_id


def test_promote_to_active_refuses_an_already_active_artifact(db_session):
    artifact = _create(db_session)
    register_as_candidate(db_session, artifact_id=artifact.artifact_id, operator="tyler")
    promote_to_active(db_session, artifact_id=artifact.artifact_id, operator="tyler")

    with pytest.raises(ValueError, match="ACTIVE"):
        promote_to_active(db_session, artifact_id=artifact.artifact_id, operator="tyler")


def test_promote_to_active_refuses_an_unsupported_family(db_session):
    artifact = _create(db_session, model_family="some-future-family")
    register_as_candidate(db_session, artifact_id=artifact.artifact_id, operator="tyler")

    with pytest.raises(ValueError, match="some-future-family"):
        promote_to_active(db_session, artifact_id=artifact.artifact_id, operator="tyler")


def test_promote_to_active_refuses_an_unknown_artifact_id(db_session):
    with pytest.raises(ValueError, match="no artifact found"):
        promote_to_active(db_session, artifact_id="artifact_does_not_exist", operator="tyler")


def test_promote_to_active_refuses_an_artifact_missing_walk_forward_metrics(db_session):
    # in-sample-only metrics (mae/rmse), no walk_forward_* keys -- exactly
    # what train_final_poisson_model(register=True) produces on its own,
    # without a walk_forward_metrics argument attached.
    artifact = _create(db_session, training_metrics={"mae": 1.2, "rmse": 1.5})
    register_as_candidate(db_session, artifact_id=artifact.artifact_id, operator="tyler")

    with pytest.raises(ValueError, match="out-of-sample walk-forward evaluation"):
        promote_to_active(db_session, artifact_id=artifact.artifact_id, operator="tyler")


def test_promote_to_active_refuses_an_artifact_with_no_training_metrics_at_all(db_session):
    artifact = _create(db_session, training_metrics={})
    register_as_candidate(db_session, artifact_id=artifact.artifact_id, operator="tyler")

    with pytest.raises(ValueError, match="out-of-sample walk-forward evaluation"):
        promote_to_active(db_session, artifact_id=artifact.artifact_id, operator="tyler")


def test_rollback_active_is_a_noop_when_nothing_is_active(db_session):
    assert rollback_active(db_session, operator="tyler", reason="just checking") is None


def test_rollback_active_falls_back_to_baseline_by_default(db_session):
    artifact = _create(db_session)
    register_as_candidate(db_session, artifact_id=artifact.artifact_id, operator="tyler")
    promote_to_active(db_session, artifact_id=artifact.artifact_id, operator="tyler")

    event = rollback_active(db_session, operator="tyler", reason="bad predictions in prod")

    assert event is not None
    assert event.to_status == "ROLLED_BACK"
    assert event.artifact_id == artifact.artifact_id
    assert current_status(db_session, artifact.artifact_id) == "ROLLED_BACK"
    assert active_artifact(db_session) is None
    resolved = resolve_active_model(db_session)
    assert resolved.active_artifact_id is None  # baseline fallback


def test_rollback_active_can_reactivate_a_specific_prior_artifact(db_session):
    first = _create(db_session, model_code_version="v-first")
    register_as_candidate(db_session, artifact_id=first.artifact_id, operator="tyler")
    promote_to_active(db_session, artifact_id=first.artifact_id, operator="tyler")

    second = _create(db_session, model_code_version="v-second")
    register_as_candidate(db_session, artifact_id=second.artifact_id, operator="tyler")
    promote_to_active(db_session, artifact_id=second.artifact_id, operator="tyler")
    # first is now RETIRED (superseded by second's promotion)

    event = rollback_active(
        db_session, operator="tyler", reason="v-second regressed", to_artifact_id=first.artifact_id
    )

    assert event is not None
    assert event.artifact_id == first.artifact_id
    assert event.to_status == "ACTIVE"
    assert event.from_status == "RETIRED"
    assert current_status(db_session, second.artifact_id) == "ROLLED_BACK"
    assert current_status(db_session, first.artifact_id) == "ACTIVE"
    resolved = active_artifact(db_session)
    assert resolved is not None
    assert resolved.artifact_id == first.artifact_id


def test_rollback_active_refuses_reactivating_a_rejected_artifact(db_session):
    currently_active = _create(db_session, model_code_version="v-active")
    register_as_candidate(db_session, artifact_id=currently_active.artifact_id, operator="tyler")
    promote_to_active(db_session, artifact_id=currently_active.artifact_id, operator="tyler")

    rejected = _create(db_session, model_code_version="v-rejected")
    record_registry_event(
        db_session,
        artifact_id=rejected.artifact_id,
        event_type="rejected",
        to_status="REJECTED",
        operator="tyler",
        reason="never should have been trained on this dataset",
        from_status=None,
    )

    # A human explicitly rejected this artifact -- rollback must not be
    # able to silently resurrect it.
    with pytest.raises(ValueError, match="REJECTED"):
        rollback_active(db_session, operator="tyler", reason="test", to_artifact_id=rejected.artifact_id)
    # The rollback of currently_active still happened -- only the
    # reactivation half was refused.
    assert current_status(db_session, currently_active.artifact_id) == "ROLLED_BACK"


def test_rollback_active_refuses_reactivating_a_never_registered_artifact(db_session):
    currently_active = _create(db_session, model_code_version="v-active")
    register_as_candidate(db_session, artifact_id=currently_active.artifact_id, operator="tyler")
    promote_to_active(db_session, artifact_id=currently_active.artifact_id, operator="tyler")

    never_registered = _create(db_session, model_code_version="v-unregistered")

    with pytest.raises(ValueError, match="None"):
        rollback_active(
            db_session, operator="tyler", reason="test", to_artifact_id=never_registered.artifact_id
        )
