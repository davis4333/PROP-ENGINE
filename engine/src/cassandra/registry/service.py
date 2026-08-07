"""Durable model artifacts + registry status events (mission directive
Phase 3A/3B). Two responsibilities, deliberately kept generic here (no
Poisson-specific knowledge) so a future model family is a drop-in --
family-specific fitting/reload logic lives in historical/train_final_model.py:

  - create_model_artifact(): writes one immutable artifact row. Every
    field the directive asks for (coefficients, provenance, checksum,
    training metrics, evaluation-report references, creator, notes) is
    supplied by the caller and never mutated afterward -- the row is
    append-only at the database grant level (see this migration's
    docstring: `e076e6061a06_model_artifacts_and_registry_events.py`).

  - record_registry_event() / register_as_candidate(): append a status-
    change event. There is no UPDATE path for an artifact's or event's
    status anywhere in this module -- "current status" is always
    current_status()'s query against the latest event, the same
    ADR 0002 "current" pattern `projections` already uses. Only
    register_as_candidate() (CANDIDATE, from_status=None) is actually
    called by any code in this build (historical/train_final_model.py's
    `cassandra train-final-model --register`) -- record_registry_event()
    is the general primitive a future promote/shadow/rollback CLI action
    would call, not wired to anything today. No function in this module
    ever decides *when* a promotion should happen; every call requires an
    explicit caller-supplied `operator` string, so nothing here can
    silently promote a model on its own.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cassandra.config import get_git_commit_sha
from cassandra.db.models.registry import MODEL_REGISTRY_STATES, ModelArtifact, ModelRegistryEvent

REGISTRY_SERVICE_VERSION = "registry-service-0.1.0"


def compute_artifact_checksum(
    *,
    model_family: str,
    model_code_version: str,
    coefficients: list[float],
    coefficient_order: list[str],
    preprocessing_rules: dict[str, Any],
    training_dataset_id: str,
) -> str:
    """A reproducibility checksum (ADR 0010's spirit, applied to a model
    artifact instead of a projection): sha256 of the fields that fully
    determine this artifact's predictions, canonicalized via sort_keys so
    the same fit always produces the same checksum regardless of dict
    key order. Deliberately excludes bookkeeping fields (artifact_id,
    trained_at, created_by) that vary per run even for byte-identical
    coefficients -- this checksum answers "would this model predict the
    same way," not "is this the same database row.\""""
    canonical = json.dumps(
        {
            "model_family": model_family,
            "model_code_version": model_code_version,
            "coefficients": coefficients,
            "coefficient_order": coefficient_order,
            "preprocessing_rules": preprocessing_rules,
            "training_dataset_id": training_dataset_id,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_model_artifact(
    session: Session,
    *,
    model_family: str,
    model_code_version: str,
    coefficients: list[float],
    coefficient_order: list[str],
    preprocessing_rules: dict[str, Any],
    training_dataset_id: str,
    dataset_builder_version: str,
    availability_policy_version: str,
    feature_set_version: str,
    training_seasons: list[int],
    training_game_types: list[str],
    training_row_count: int,
    trained_at: datetime,
    dependency_versions: dict[str, str],
    training_metrics: dict[str, Any],
    evaluation_report_ids: list[str],
    created_by: str,
    notes: str | None = None,
) -> ModelArtifact:
    """Writes one durable, append-only model artifact row. `coefficients`
    must include the intercept term at coefficient_order[0] == "intercept"
    (matching historical/challenger_poisson.py's design-row convention) --
    `intercept` is stored again on its own column purely as a query
    convenience, always coefficients[0]."""
    if not coefficient_order or coefficient_order[0] != "intercept":
        raise ValueError(f"coefficient_order must start with 'intercept', got {coefficient_order!r}")
    artifact_id = f"artifact_{uuid.uuid4().hex[:12]}"
    fitted_model_version = f"{model_code_version}+{artifact_id}"
    checksum = compute_artifact_checksum(
        model_family=model_family,
        model_code_version=model_code_version,
        coefficients=coefficients,
        coefficient_order=coefficient_order,
        preprocessing_rules=preprocessing_rules,
        training_dataset_id=training_dataset_id,
    )
    artifact = ModelArtifact(
        artifact_id=artifact_id,
        model_family=model_family,
        model_code_version=model_code_version,
        fitted_model_version=fitted_model_version,
        coefficients=coefficients,
        coefficient_order=coefficient_order,
        intercept=coefficients[0],
        preprocessing_rules=preprocessing_rules,
        training_dataset_id=training_dataset_id,
        dataset_builder_version=dataset_builder_version,
        availability_policy_version=availability_policy_version,
        feature_set_version=feature_set_version,
        training_seasons=training_seasons,
        training_game_types=training_game_types,
        training_row_count=training_row_count,
        trained_at=trained_at,
        source_git_sha=get_git_commit_sha(),
        artifact_checksum=checksum,
        dependency_versions=dependency_versions,
        training_metrics=training_metrics,
        evaluation_report_ids=evaluation_report_ids,
        notes=notes,
        created_by=created_by,
    )
    session.add(artifact)
    session.flush()
    return artifact


def record_registry_event(
    session: Session,
    *,
    artifact_id: str,
    event_type: str,
    to_status: str,
    operator: str,
    reason: str | None = None,
    from_status: str | None = None,
) -> ModelRegistryEvent:
    """Appends one registry status-change event. Never mutates a prior
    event or the artifact itself -- callers derive "current status" via
    current_status() rather than trusting any single stored flag."""
    if to_status not in MODEL_REGISTRY_STATES:
        raise ValueError(f"to_status must be one of {MODEL_REGISTRY_STATES}, got {to_status!r}")
    event = ModelRegistryEvent(
        event_id=f"regevt_{uuid.uuid4().hex[:12]}",
        artifact_id=artifact_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        operator=operator,
        reason=reason,
        git_commit_sha=get_git_commit_sha(),
    )
    session.add(event)
    session.flush()
    return event


def register_as_candidate(
    session: Session, *, artifact_id: str, operator: str, reason: str | None = None
) -> ModelRegistryEvent:
    """The only registry transition any code in this build actually
    calls (historical/train_final_model.py). A freshly created artifact
    has no prior status (from_status=None) -- registering it is what
    gives it its first one, CANDIDATE. Never auto-promotes further: no
    other status is reachable from here without a separate, explicit
    future call."""
    return record_registry_event(
        session,
        artifact_id=artifact_id,
        event_type="registered",
        to_status="CANDIDATE",
        operator=operator,
        reason=reason,
        from_status=None,
    )


def current_status(session: Session, artifact_id: str) -> str | None:
    """The artifact's current status, derived from its latest registry
    event -- None if the artifact has never been registered at all (a
    fitted-but-not-registered artifact, e.g. `train-final-model` run
    without `--register`)."""
    stmt = (
        select(ModelRegistryEvent.to_status)
        .where(ModelRegistryEvent.artifact_id == artifact_id)
        .order_by(ModelRegistryEvent.occurred_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


__all__ = [
    "REGISTRY_SERVICE_VERSION",
    "compute_artifact_checksum",
    "create_model_artifact",
    "current_status",
    "record_registry_event",
    "register_as_candidate",
]
