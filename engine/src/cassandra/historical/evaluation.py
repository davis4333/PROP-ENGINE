"""Evaluates a `StrikeoutModel` against a frozen training dataset
(`historical/dataset_builder.py`) -- MAE, RMSE, mean bias, Poisson
deviance, and calibration/Brier score at a fixed set of illustrative
half-integer thresholds (docs/TRAINING_READINESS_REPORT.md's "next
steps"). No real historical market lines exist in this dataset (out of
scope per the mission directive -- see `TRAINING_DATASET_SPEC.md`), so
"calibration" here means: for each threshold, compare the model's own
predicted P(strikeouts > threshold) against the realized frequency of
that outcome across the dataset -- a property of the model's probability
estimates, not a real betting-line hit rate. Every report this module
produces must be labeled `HISTORICAL_RECONSTRUCTION`/`BACKTEST`, never
`LIVE` (CLAUDE.md non-negotiable #8) -- this module never writes to
`projections`/`grades`, only to its own frozen evaluation-report files.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cassandra.models.interface import StrikeoutModel

EVALUATION_MODULE_VERSION = "historical-evaluation-0.1.0"

# Illustrative half-integer strikeout thresholds -- not derived from any
# real market line (none exist in this dataset). Chosen to span the
# typical starting-pitcher strikeout range.
CALIBRATION_THRESHOLDS = (3.5, 4.5, 5.5, 6.5, 7.5, 8.5)

RECORD_LABEL = "HISTORICAL_RECONSTRUCTION"


@dataclass(frozen=True)
class ThresholdCalibration:
    threshold: float
    n: int
    mean_predicted_prob_over: float
    empirical_over_rate: float
    brier_score: float


@dataclass(frozen=True)
class EvaluationReport:
    evaluation_id: str
    record_label: str
    evaluation_module_version: str
    dataset_id: str
    model_version: str
    evaluated_at: str
    n_rows: int
    n_rows_skipped_missing_label: int
    mae: float
    rmse: float
    mean_bias: float
    mean_poisson_deviance: float
    calibration: list[ThresholdCalibration]
    breakdown_by_recent_k_rate_tier: dict[str, dict[str, float]]


def _poisson_deviance(actual: int, predicted_mean: float) -> float:
    """2 * (actual*ln(actual/predicted) - (actual - predicted)), with the
    actual=0 term's well-defined limit (actual*ln(actual/predicted) -> 0)
    handled explicitly rather than raising on log(0)."""
    predicted_mean = max(predicted_mean, 1e-9)
    log_term = 0.0 if actual == 0 else actual * math.log(actual / predicted_mean)
    return 2.0 * (log_term - (actual - predicted_mean))


def evaluate_model(rows: list[dict[str, Any]], model: StrikeoutModel, *, dataset_id: str) -> EvaluationReport:
    """Runs `model.predict()` against every row's already-frozen feature
    fields and compares to that row's real `actual_strikeouts` label.
    Rows with a missing label are skipped and counted, never silently
    dropped without a trace."""
    errors: list[float] = []
    squared_errors: list[float] = []
    deviances: list[float] = []
    calibration_hits: dict[float, list[tuple[float, bool]]] = {t: [] for t in CALIBRATION_THRESHOLDS}
    tier_errors: dict[str, list[float]] = {}
    skipped = 0

    for row in rows:
        actual = row.get("actual_strikeouts")
        if actual is None:
            skipped += 1
            continue
        distribution = model.predict(row)
        predicted_mean = distribution.mean
        error = predicted_mean - actual
        errors.append(error)
        squared_errors.append(error**2)
        deviances.append(_poisson_deviance(actual, predicted_mean))

        for threshold in CALIBRATION_THRESHOLDS:
            predicted_prob_over = 1.0 - distribution.cdf(math.floor(threshold))
            actual_over = actual > threshold
            calibration_hits[threshold].append((predicted_prob_over, actual_over))

        tier = row.get("recent_k_rate_tier", "unknown")
        tier_errors.setdefault(tier, []).append(abs(error))

    n = len(errors)
    mae = sum(abs(e) for e in errors) / n if n else 0.0
    rmse = math.sqrt(sum(squared_errors) / n) if n else 0.0
    mean_bias = sum(errors) / n if n else 0.0
    mean_deviance = sum(deviances) / n if n else 0.0

    calibration = [
        ThresholdCalibration(
            threshold=threshold,
            n=len(hits),
            mean_predicted_prob_over=(sum(p for p, _ in hits) / len(hits)) if hits else 0.0,
            empirical_over_rate=(sum(1 for _, over in hits if over) / len(hits)) if hits else 0.0,
            brier_score=(sum((p - (1.0 if over else 0.0)) ** 2 for p, over in hits) / len(hits))
            if hits
            else 0.0,
        )
        for threshold, hits in calibration_hits.items()
    ]

    breakdown = {
        tier: {"n": len(abs_errors), "mae": sum(abs_errors) / len(abs_errors)}
        for tier, abs_errors in tier_errors.items()
        if abs_errors
    }

    return EvaluationReport(
        evaluation_id=f"eval_{uuid.uuid4().hex[:12]}",
        record_label=RECORD_LABEL,
        evaluation_module_version=EVALUATION_MODULE_VERSION,
        dataset_id=dataset_id,
        model_version=model.model_version,
        evaluated_at=datetime.now(UTC).isoformat(),
        n_rows=n,
        n_rows_skipped_missing_label=skipped,
        mae=mae,
        rmse=rmse,
        mean_bias=mean_bias,
        mean_poisson_deviance=mean_deviance,
        calibration=calibration,
        breakdown_by_recent_k_rate_tier=breakdown,
    )


def write_evaluation_report(report: EvaluationReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{report.evaluation_id}.json"
    path.write_text(json.dumps(asdict(report), indent=2))
    return path


__all__ = [
    "CALIBRATION_THRESHOLDS",
    "EVALUATION_MODULE_VERSION",
    "RECORD_LABEL",
    "EvaluationReport",
    "ThresholdCalibration",
    "evaluate_model",
    "write_evaluation_report",
]
