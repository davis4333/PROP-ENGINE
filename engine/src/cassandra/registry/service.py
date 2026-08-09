"""Durable model artifacts + registry status events (mission directive
Phase 3A/3B) and resolving which model the LIVE pipeline should actually
predict with (Phase 4). Deliberately kept generic here (no Poisson-
specific fitting knowledge) so a future model family is a drop-in --
family-specific fitting logic lives in historical/train_final_model.py;
family-specific *reconstruction* (the reverse of fitting -- turning a
stored artifact's coefficients back into a usable model) lives here in
resolve_active_model(), since that has to run from the live pipeline,
not just training tooling.

  - create_model_artifact(): writes one immutable artifact row. Every
    field the directive asks for (coefficients, provenance, checksum,
    training metrics, evaluation-report references, creator, notes) is
    supplied by the caller and never mutated afterward -- the row is
    append-only at the database grant level (see this migration's
    docstring: `e076e6061a06_model_artifacts_and_registry_events.py`).

  - record_registry_event() / register_as_candidate() / promote_to_active()
    / rollback_active(): append a status-change event. There is no UPDATE
    path for an artifact's or event's status anywhere in this module --
    "current status" is always current_status()'s query against the
    latest event, the same ADR 0002 "current" pattern `projections`
    already uses. Every one of these requires an explicit caller-supplied
    `operator` string, so nothing here can silently promote/activate a
    model on its own -- promotion only ever happens because a human (or a
    script acting under a human's explicit instruction) called
    promote_to_active() with their own identity attached.

  - resolve_active_model(): the live pipeline's one entry point for
    "which model should I actually use right now." Returns the permanent,
    unmodified baseline whenever no artifact is ACTIVE (including the
    common case where nothing has ever been promoted) -- the directive's
    "permanent baseline as guaranteed fallback" requirement, enforced
    structurally rather than by convention: there is no code path here
    that can return an empty/broken model.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cassandra.config import get_git_commit_sha
from cassandra.db.models.registry import MODEL_REGISTRY_STATES, ModelArtifact, ModelRegistryEvent
from cassandra.models.baseline import MODEL_VERSION as BASELINE_MODEL_VERSION
from cassandra.models.baseline import BaselinePoissonModel
from cassandra.models.interface import StrikeoutModel
from cassandra.models.negative_binomial_regression import NegativeBinomialRegressionModel
from cassandra.models.poisson_regression import PoissonRegressionModel

REGISTRY_SERVICE_VERSION = "registry-service-0.5.0"

# model_family values resolve_active_model() knows how to reconstruct.
# Kept explicit and checked (rather than a bare try/except around a
# dispatch dict) so an artifact with an unsupported family fails loudly
# with a clear message instead of silently falling back to the baseline
# -- an operator who promoted a real artifact needs to know their
# promotion isn't actually taking effect, not have it silently ignored.
SUPPORTED_LIVE_MODEL_FAMILIES = ("poisson-regression", "negative-binomial-regression")


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
    without `--register`). Orders by `sequence`, not `occurred_at`: two
    events written in the same transaction (e.g. promote_to_active()'s
    retire-then-activate pair) get identical `occurred_at` values since
    Postgres's `now()` is frozen at transaction start, but `sequence`
    (a BIGSERIAL, evaluated per statement) is always a real total order."""
    stmt = (
        select(ModelRegistryEvent.to_status)
        .where(ModelRegistryEvent.artifact_id == artifact_id)
        .order_by(ModelRegistryEvent.sequence.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def active_artifact(session: Session) -> ModelArtifact | None:
    """The artifact whose latest registry event has to_status == "ACTIVE",
    or None if no artifact is currently active. Deliberately uses
    scalar_one_or_none() (raises on more than one match) rather than
    silently picking one: promote_to_active() always atomically retires
    whatever was previously ACTIVE in the same transaction it activates a
    new one, so more than one ACTIVE artifact existing at once is a real
    data-integrity violation this should surface loudly, never paper
    over by guessing which one "really" counts."""
    latest_per_artifact = (
        select(
            ModelRegistryEvent.artifact_id,
            ModelRegistryEvent.to_status,
            func.row_number()
            .over(
                partition_by=ModelRegistryEvent.artifact_id,
                order_by=ModelRegistryEvent.sequence.desc(),
            )
            .label("rn"),
        )
    ).subquery()
    stmt = (
        select(ModelArtifact)
        .join(latest_per_artifact, latest_per_artifact.c.artifact_id == ModelArtifact.artifact_id)
        .where(latest_per_artifact.c.rn == 1, latest_per_artifact.c.to_status == "ACTIVE")
    )
    return session.execute(stmt).scalar_one_or_none()


def pending_candidates(session: Session) -> list[ModelArtifact]:
    """Every artifact whose latest registry event's to_status is
    CANDIDATE or APPROVED (see PROMOTABLE_STATUSES) -- i.e. registered
    but neither promoted nor rejected/retired yet. Purely for visibility
    (api/routers/admin.py's AdminStatusResponse.pending_model_candidates)
    so a human knows there's something to review, whether it was
    hand-registered via `train-final-model --register` or produced by
    orchestration/retraining_scheduler.py's automatic path -- never used
    to decide anything on its own. Ordered newest-first (most recently
    registered/approved first)."""
    latest_per_artifact = (
        select(
            ModelRegistryEvent.artifact_id,
            ModelRegistryEvent.to_status,
            ModelRegistryEvent.sequence,
            func.row_number()
            .over(
                partition_by=ModelRegistryEvent.artifact_id,
                order_by=ModelRegistryEvent.sequence.desc(),
            )
            .label("rn"),
        )
    ).subquery()
    stmt = (
        select(ModelArtifact)
        .join(latest_per_artifact, latest_per_artifact.c.artifact_id == ModelArtifact.artifact_id)
        .where(latest_per_artifact.c.rn == 1, latest_per_artifact.c.to_status.in_(PROMOTABLE_STATUSES))
        .order_by(latest_per_artifact.c.sequence.desc())
    )
    return list(session.execute(stmt).scalars())


# Statuses promote_to_active() will accept as a promotion's starting
# point. Deliberately excludes ACTIVE (already active -- promoting it
# again would just retire-then-reactivate the same artifact, a
# meaningless no-op event pair), RETIRED/REJECTED/ROLLED_BACK (all
# terminal -- an artifact that left ACTIVE status once shouldn't silently
# re-enter it through the normal promotion path; use rollback_active()'s
# explicit to_artifact_id if reactivating a specific prior artifact is
# genuinely intended), and None (never registered at all).
PROMOTABLE_STATUSES = ("CANDIDATE", "APPROVED")

# Statuses rollback_active()'s to_artifact_id may reactivate from --
# broader than PROMOTABLE_STATUSES since a rollback's whole point is
# reaching back to something that already left ACTIVE (RETIRED or
# ROLLED_BACK), not just a fresh CANDIDATE.
ROLLBACK_REACTIVATABLE_STATUSES = ("CANDIDATE", "APPROVED", "RETIRED", "ROLLED_BACK")

# promote_to_active() requires both of these keys in training_metrics --
# proof a genuine out-of-sample walk-forward comparison actually ran
# before this artifact reaches ACTIVE, not just train_final_poisson_model's
# always-populated in-sample fit-quality numbers (mae/rmse/mean_bias/
# mean_poisson_deviance above are computed against the SAME rows the
# model was fit on, which is optimistic by construction -- see
# train_final_model.py's own docstring). Found and fixed after an audit:
# nothing previously stopped `train-final-model --register` followed
# directly by `promote-model` without ever running
# `train-walk-forward-challenger` first. historical/train_final_model.py's
# optional walk_forward_metrics parameter is what populates these keys;
# orchestration/retraining_scheduler.py's automatic path always supplies
# them (it runs walk-forward validation itself before ever training a
# final model), and the CLI's `train-final-model --after-walk-forward-
# report` flag is how a human attaches them to a manually-trained
# artifact.
REQUIRED_WALK_FORWARD_METRIC_KEYS = (
    "walk_forward_aggregate_baseline_mae",
    "walk_forward_aggregate_challenger_mae",
)


def promote_to_active(
    session: Session, *, artifact_id: str, operator: str, reason: str | None = None
) -> ModelRegistryEvent:
    """Promotes `artifact_id` to ACTIVE, atomically retiring whatever was
    previously ACTIVE (if anything) in the SAME transaction -- the
    directive's "exactly one ACTIVE model at a time" requirement,
    enforced here rather than left to convention (see active_artifact()'s
    own docstring for why that matters). Refuses to promote an artifact
    that isn't currently CANDIDATE/APPROVED (see PROMOTABLE_STATUSES), whose
    model_family resolve_active_model() can't actually reconstruct, or that
    was never evaluated out-of-sample (see REQUIRED_WALK_FORWARD_METRIC_KEYS)
    -- all three would otherwise silently break or degrade every future
    run_slate() call; each gets a clear error at promotion time instead."""
    artifact = session.get(ModelArtifact, artifact_id)
    if artifact is None:
        raise ValueError(f"no artifact found with artifact_id={artifact_id!r}")
    status = current_status(session, artifact_id)
    if status not in PROMOTABLE_STATUSES:
        raise ValueError(
            f"cannot promote artifact {artifact_id}: current status is {status!r}, expected one of "
            f"{PROMOTABLE_STATUSES}. An artifact must be registered "
            "(`cassandra train-final-model --register`) before it can be promoted."
        )
    if artifact.model_family not in SUPPORTED_LIVE_MODEL_FAMILIES:
        raise ValueError(
            f"cannot promote artifact {artifact_id}: model_family {artifact.model_family!r} is not "
            f"one resolve_active_model() can serve (supported: {SUPPORTED_LIVE_MODEL_FAMILIES})"
        )
    training_metrics = artifact.training_metrics or {}
    missing_keys = [k for k in REQUIRED_WALK_FORWARD_METRIC_KEYS if k not in training_metrics]
    if missing_keys:
        raise ValueError(
            f"cannot promote artifact {artifact_id}: training_metrics is missing out-of-sample "
            f"walk-forward evaluation ({', '.join(missing_keys)}). In-sample fit-quality numbers "
            "alone are not enough to promote to production -- run "
            "`cassandra train-walk-forward-challenger` first, then re-train with "
            "`cassandra train-final-model --after-walk-forward-report <path>` so the comparison "
            "is attached to this artifact."
        )

    previous = active_artifact(session)
    if previous is not None:
        record_registry_event(
            session,
            artifact_id=previous.artifact_id,
            event_type="retired",
            to_status="RETIRED",
            operator=operator,
            reason=f"superseded by promotion of {artifact_id}",
            from_status="ACTIVE",
        )
    return record_registry_event(
        session,
        artifact_id=artifact_id,
        event_type="activated",
        to_status="ACTIVE",
        operator=operator,
        reason=reason,
        from_status=status,
    )


def rollback_active(
    session: Session, *, operator: str, reason: str, to_artifact_id: str | None = None
) -> ModelRegistryEvent | None:
    """Retires whatever is currently ACTIVE, marking it ROLLED_BACK (not
    RETIRED -- a rollback is an emergency reversal, not a routine
    supersession). With `to_artifact_id=None` (the common case), nothing
    new becomes ACTIVE -- resolve_active_model() falls straight back to
    the permanent baseline on its very next call, no second artifact
    required. With `to_artifact_id` set, that specific prior artifact
    (must currently be CANDIDATE/APPROVED/RETIRED/ROLLED_BACK -- see
    ROLLBACK_REACTIVATABLE_STATUSES) is reactivated in the same call.

    Returns None if nothing was ACTIVE to begin with -- a harmless no-op,
    not an error, since rolling back an already-inactive system is safe.
    `reason` is required (unlike promote_to_active()'s optional one): a
    rollback is by definition an unplanned reversal and should always be
    explained for whoever reads the registry history later."""
    current = active_artifact(session)
    if current is None:
        return None
    rollback_event = record_registry_event(
        session,
        artifact_id=current.artifact_id,
        event_type="rolled_back",
        to_status="ROLLED_BACK",
        operator=operator,
        reason=reason,
        from_status="ACTIVE",
    )
    if to_artifact_id is None:
        return rollback_event

    target_status = current_status(session, to_artifact_id)
    if target_status not in ROLLBACK_REACTIVATABLE_STATUSES:
        raise ValueError(
            f"cannot roll back to artifact {to_artifact_id}: current status is {target_status!r}, "
            f"expected one of {ROLLBACK_REACTIVATABLE_STATUSES}"
        )
    return record_registry_event(
        session,
        artifact_id=to_artifact_id,
        event_type="activated",
        to_status="ACTIVE",
        operator=operator,
        reason=f"reactivated during rollback: {reason}",
        from_status=target_status,
    )


@dataclass(frozen=True)
class ResolvedModel:
    """What orchestration/run_slate.py's PROJECT stage actually needs:
    a ready-to-call model, the exact version string to record on every
    projection it produces (a specific artifact's fitted_model_version
    when serving a promoted challenger -- NOT the shared model_code_version
    every artifact of that family has in common, so a live projection is
    traceable back to the one artifact that produced it), and the
    artifact_id (if any) for anything that wants to log/display it."""

    model: StrikeoutModel
    model_version: str
    active_artifact_id: str | None


def resolve_active_model(session: Session) -> ResolvedModel:
    """The live pipeline's single entry point for "which model should I
    actually predict with right now." Returns the permanent, unmodified
    baseline whenever no artifact is ACTIVE -- structurally guaranteed,
    not by convention: every branch below either returns a real model or
    raises (on a data-integrity problem this project's own philosophy
    says must fail loudly, never silently degrade -- see
    active_artifact()'s own docstring), so there is no path that returns
    nothing."""
    artifact = active_artifact(session)
    if artifact is None:
        return ResolvedModel(
            model=BaselinePoissonModel(), model_version=BASELINE_MODEL_VERSION, active_artifact_id=None
        )
    if artifact.model_family == "poisson-regression":
        model: StrikeoutModel = PoissonRegressionModel(
            coefficients=tuple(float(c) for c in artifact.coefficients)
        )
        return ResolvedModel(
            model=model, model_version=artifact.fitted_model_version, active_artifact_id=artifact.artifact_id
        )
    if artifact.model_family == "negative-binomial-regression":
        # `dispersion` isn't part of coefficients/coefficient_order (those
        # stay strictly aligned with design_row()'s mean-regression order,
        # same as the poisson-regression family) -- it lives in
        # preprocessing_rules, the field db/models/registry.py's own
        # docstring says is exactly for family-specific values with no
        # fixed shape across families.
        model = NegativeBinomialRegressionModel(
            coefficients=tuple(float(c) for c in artifact.coefficients),
            dispersion=float(artifact.preprocessing_rules["dispersion"]),
        )
        return ResolvedModel(
            model=model, model_version=artifact.fitted_model_version, active_artifact_id=artifact.artifact_id
        )
    raise ValueError(
        f"active artifact {artifact.artifact_id} has model_family "
        f"{artifact.model_family!r}, which resolve_active_model() doesn't know how to "
        f"reconstruct (supported: {SUPPORTED_LIVE_MODEL_FAMILIES}). This should be "
        "structurally impossible -- promote_to_active() only accepts artifacts whose "
        "family it can reconstruct -- so seeing this means that guard was bypassed."
    )


__all__ = [
    "PROMOTABLE_STATUSES",
    "REGISTRY_SERVICE_VERSION",
    "REQUIRED_WALK_FORWARD_METRIC_KEYS",
    "ROLLBACK_REACTIVATABLE_STATUSES",
    "SUPPORTED_LIVE_MODEL_FAMILIES",
    "ResolvedModel",
    "active_artifact",
    "compute_artifact_checksum",
    "create_model_artifact",
    "current_status",
    "pending_candidates",
    "promote_to_active",
    "record_registry_event",
    "register_as_candidate",
    "resolve_active_model",
    "rollback_active",
]
