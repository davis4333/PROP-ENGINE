"""Fits and durably registers a FINAL (not walk-forward-folded) Poisson-
regression challenger against an entire frozen training dataset (mission
directive Phase 3C). walk_forward.py answers "is this model family
competitive against the baseline"; this module answers "freeze the exact
artifact a human might later promote to production."

Never auto-promotes: `train_final_poisson_model()` only ever creates an
artifact and, if `register=True`, registers it as CANDIDATE --
registry/service.py's module docstring explains why nothing here can
reach any status past that on its own.

Deliberately manages its own `session_scope()` calls internally rather
than taking a caller-supplied session (unlike most orchestration
functions in this codebase, e.g. run_slate()) -- the artifact write must
actually COMMIT before the reload-and-validate step below can prove a
genuine database round-trip; both happening inside one still-open
caller transaction would make the "reload" trivially see the same
uncommitted in-memory row, proving nothing. Same reasoning as
orchestration/run_slate.py's `_record_failed_run` needing its own
separate session, added during Phase 1B.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from cassandra.db.models.registry import ModelArtifact
from cassandra.db.session import session_scope
from cassandra.historical.challenger_poisson import (
    COEFFICIENT_NAMES,
    CONVERGENCE_TOL,
    DEFAULT_REST_DAYS,
    MAX_IRLS_ITERATIONS,
    POISSON_CHALLENGER_VERSION,
    RIDGE_LAMBDA,
    PoissonRegressionModel,
    fit_poisson_regression,
)
from cassandra.historical.dataset_builder import DatasetManifest
from cassandra.historical.evaluation import evaluate_model, write_evaluation_report
from cassandra.registry.service import create_model_artifact, register_as_candidate

TRAIN_FINAL_MODEL_MODULE_VERSION = "train-final-model-0.1.0"

SUPPORTED_MODEL_FAMILIES = ("poisson-regression",)


@dataclass(frozen=True)
class TrainFinalModelResult:
    artifact_id: str
    fitted_model_version: str
    evaluation_id: str
    registered: bool
    registry_event_id: str | None
    training_metrics: dict[str, float]


def _poisson_preprocessing_rules() -> dict[str, Any]:
    """Fit-time/predict-time constants actually in effect for this
    family's code today -- pure provenance. A reload never re-derives
    behavior from this dict; it always reuses the real
    PoissonRegressionModel.predict() implementation, so this can't drift
    out of sync with actual prediction behavior the way a re-implemented
    copy could."""
    return {
        "rest_days_default": DEFAULT_REST_DAYS,
        "prediction_eta_clip_max": 20.0,
        "fit_eta_clip_min": -20.0,
        "fit_eta_clip_max": 20.0,
        "fit_mu_clip_min": 1e-6,
        "regularization": {"method": "ridge", "lambda": RIDGE_LAMBDA},
        "max_irls_iterations": MAX_IRLS_ITERATIONS,
        "convergence_tol": CONVERGENCE_TOL,
    }


def train_final_poisson_model(
    *,
    manifest: DatasetManifest,
    rows: list[dict[str, Any]],
    operator: str,
    output_dir: Path,
    register: bool,
    notes: str | None = None,
) -> TrainFinalModelResult:
    """Loads ALL eligible rows from one frozen dataset (no walk-forward
    holdout), fits a Poisson-regression challenger, evaluates it
    in-sample (there is no held-out data in a final-model fit by design
    -- see historical/walk_forward.py for the held-out comparison tool),
    writes a durable artifact, proves the artifact reloads byte-
    identically from the database and predicts identically once
    reloaded, and -- only if `register` is True -- registers it as
    CANDIDATE."""
    fitted = fit_poisson_regression(rows)
    report = evaluate_model(rows, fitted, dataset_id=manifest.dataset_id)
    write_evaluation_report(report, output_dir / "evaluations")

    coefficients = list(fitted.coefficients)
    if len(coefficients) != len(COEFFICIENT_NAMES):
        raise ValueError(
            f"fit produced {len(coefficients)} coefficients but COEFFICIENT_NAMES has "
            f"{len(COEFFICIENT_NAMES)} entries -- challenger_poisson.py's design row and "
            "COEFFICIENT_NAMES have drifted out of sync"
        )

    training_metrics = {
        "mae": report.mae,
        "rmse": report.rmse,
        "mean_bias": report.mean_bias,
        "mean_poisson_deviance": report.mean_poisson_deviance,
    }

    with session_scope() as write_session:
        artifact = create_model_artifact(
            write_session,
            model_family="poisson-regression",
            model_code_version=POISSON_CHALLENGER_VERSION,
            coefficients=coefficients,
            coefficient_order=list(COEFFICIENT_NAMES),
            preprocessing_rules=_poisson_preprocessing_rules(),
            training_dataset_id=manifest.dataset_id,
            dataset_builder_version=manifest.dataset_builder_version,
            availability_policy_version=manifest.availability_policy_version,
            feature_set_version=manifest.feature_set_version,
            training_seasons=manifest.seasons,
            training_game_types=manifest.game_types,
            training_row_count=len(rows),
            trained_at=datetime.now(UTC),
            dependency_versions={"numpy": np.__version__},
            training_metrics=training_metrics,
            evaluation_report_ids=[report.evaluation_id],
            created_by=operator,
            notes=notes,
        )
        artifact_id = artifact.artifact_id
        fitted_model_version = artifact.fitted_model_version
    # write_session committed on exiting the `with` block above -- the
    # artifact row is now durable before the reload step below runs.

    # Validate serialization/reload (mission directive 3C): a genuinely
    # separate session/transaction re-reads the row (proving a real
    # JSONB round-trip, not just re-reading the same in-memory ORM
    # object), reconstructs a model from it, and confirms both the raw
    # coefficients AND the reloaded model's predictions are identical to
    # the original fit -- "evaluates the reloaded artifact," not just
    # "the numbers look the same."
    with session_scope() as reload_session:
        reloaded_row = reload_session.get(ModelArtifact, artifact_id)
        if reloaded_row is None:
            raise RuntimeError(f"artifact {artifact_id} vanished immediately after being written")
        reloaded_coefficients = tuple(float(c) for c in reloaded_row.coefficients)

    if reloaded_coefficients != fitted.coefficients:
        raise RuntimeError(
            f"artifact {artifact_id} failed round-trip validation: stored coefficients "
            f"{reloaded_coefficients} do not exactly match the fitted coefficients "
            f"{fitted.coefficients}"
        )
    reloaded_model = PoissonRegressionModel(coefficients=reloaded_coefficients)
    reloaded_report = evaluate_model(rows, reloaded_model, dataset_id=manifest.dataset_id)
    if reloaded_report.mae != report.mae or reloaded_report.rmse != report.rmse:
        raise RuntimeError(
            f"artifact {artifact_id} failed round-trip validation: the reloaded model's "
            f"evaluation (mae={reloaded_report.mae}, rmse={reloaded_report.rmse}) does not "
            f"exactly match the original fit's (mae={report.mae}, rmse={report.rmse})"
        )

    registry_event_id: str | None = None
    if register:
        with session_scope() as register_session:
            event = register_as_candidate(register_session, artifact_id=artifact_id, operator=operator)
            registry_event_id = event.event_id

    return TrainFinalModelResult(
        artifact_id=artifact_id,
        fitted_model_version=fitted_model_version,
        evaluation_id=report.evaluation_id,
        registered=register,
        registry_event_id=registry_event_id,
        training_metrics=training_metrics,
    )


__all__ = [
    "SUPPORTED_MODEL_FAMILIES",
    "TRAIN_FINAL_MODEL_MODULE_VERSION",
    "TrainFinalModelResult",
    "train_final_poisson_model",
]
