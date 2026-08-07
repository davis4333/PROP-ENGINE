"""Durable model artifacts + the model registry (mission directive Phase
3): every fitted model gets a permanent, append-only artifact record
(coefficients, full training provenance, checksum) and status changes
(CANDIDATE -> SHADOW -> APPROVED -> ACTIVE -> RETIRED, or REJECTED/
ROLLED_BACK) are tracked as append-only events, never a mutable status
column -- "current status" is always derived by querying the latest
event for an artifact_id, the same ADR 0002 pattern `projections` already
uses for "current" (see db/models/projection.py). No auto-promotion is
possible here structurally: nothing in this module ever mutates a row to
change its status, and nothing here decides *when* to promote -- that's
an explicit human/CLI action (registry/service.py), never triggered by
training or evaluation code on its own.

Both tables are append-only at the database grant level (see the
`model_artifacts`/`model_registry_events` migration) -- UPDATE/DELETE are
blocked by the same `cassandra_block_immutable_mutation` trigger
`raw_*`/`projections`/`grades`/`audit_events` use, and TRUNCATE is
revoked, matching CLAUDE.md non-negotiable #3.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cassandra.db.base import Base

# The full state vocabulary the registry supports. Only "registered" (->
# CANDIDATE) is actually wired up to a CLI action today
# (`cassandra train-final-model --register`, historical/train_final_model.py)
# -- promotion/shadow/rollback actions are real future work, not invented
# here; see docs/FINAL_COMPLETION_WORKLOG.md's 3B entry for why the rest
# of the vocabulary exists now even though nothing calls it yet.
MODEL_REGISTRY_STATES = (
    "CANDIDATE",
    "SHADOW",
    "APPROVED",
    "ACTIVE",
    "RETIRED",
    "REJECTED",
    "ROLLED_BACK",
)


class ModelArtifact(Base):
    __tablename__ = "model_artifacts"

    artifact_id: Mapped[str] = mapped_column(String, primary_key=True)
    model_family: Mapped[str] = mapped_column(String, nullable=False)
    # The fitting CODE's own semantic version (e.g. challenger_poisson.py's
    # POISSON_CHALLENGER_VERSION) -- shared across every artifact fit by
    # the same code. Distinct from fitted_model_version below, which is
    # unique per artifact.
    model_code_version: Mapped[str] = mapped_column(String, nullable=False)
    fitted_model_version: Mapped[str] = mapped_column(String, nullable=False, unique=True)

    # coefficient_order[i] names coefficients[i] -- e.g. ["intercept",
    # "log1p_expected_bf", "recent_k_rate", "rest_days",
    # "rest_days_missing"]. `intercept` is redundantly stored on its own
    # column too (a direct-query convenience); coefficients[0] together
    # with coefficient_order[0] == "intercept" remains the single source
    # of truth a reload reconstructs the model from.
    coefficients: Mapped[list] = mapped_column(JSONB, nullable=False)
    coefficient_order: Mapped[list] = mapped_column(JSONB, nullable=False)
    intercept: Mapped[float] = mapped_column(Numeric, nullable=False)

    # Default-value handling, clipping bounds, and regularization
    # hyperparameters actually used for this fit -- e.g. {"rest_days_
    # default": 5.0, "eta_clip_max": 20.0, "mu_clip_min": 1e-6,
    # "regularization": {"method": "ridge", "lambda": 1.0}}. Bundled into
    # one field rather than several near-empty columns since these are
    # inherently model-family-specific and have no fixed shape across
    # families.
    preprocessing_rules: Mapped[dict] = mapped_column(JSONB, nullable=False)

    training_dataset_id: Mapped[str] = mapped_column(String, nullable=False)
    dataset_builder_version: Mapped[str] = mapped_column(String, nullable=False)
    availability_policy_version: Mapped[str] = mapped_column(String, nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String, nullable=False)
    training_seasons: Mapped[list] = mapped_column(JSONB, nullable=False)
    training_game_types: Mapped[list] = mapped_column(JSONB, nullable=False)
    training_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    source_git_sha: Mapped[str | None] = mapped_column(String)
    artifact_checksum: Mapped[str] = mapped_column(String, nullable=False)
    dependency_versions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    training_metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # historical/evaluation.py EvaluationReport.evaluation_id values --
    # the reports themselves live in their own frozen JSON files (see
    # write_evaluation_report); this is a pointer list, not a copy.
    evaluation_report_ids: Mapped[list] = mapped_column(JSONB, nullable=False)

    notes: Mapped[str | None] = mapped_column(String)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelRegistryEvent(Base):
    __tablename__ = "model_registry_events"
    __table_args__ = (
        CheckConstraint(f"to_status IN {MODEL_REGISTRY_STATES}", name="ck_model_registry_events_to_status"),
        Index("ix_model_registry_events_artifact_id", "artifact_id"),
    )

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    artifact_id: Mapped[str] = mapped_column(
        String, ForeignKey("model_artifacts.artifact_id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    from_status: Mapped[str | None] = mapped_column(String)
    to_status: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    operator: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str | None] = mapped_column(String)
    # Snapshot of config.get_git_commit_sha() at the moment of this event
    # -- independent of the artifact's own source_git_sha (the commit
    # that TRAINED it), since a promotion/rollback can happen from a
    # different deployment than the one that produced the artifact.
    git_commit_sha: Mapped[str | None] = mapped_column(String)
