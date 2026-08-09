"""Time-ordered walk-forward validation over a frozen training dataset
(mission directive Phase 7: "time-ordered walk-forward validation --
train on earlier dates, validate on later dates, roll forward, never
train on games after the evaluation game").

Deliberately not k-fold cross-validation: an ordinary k-fold split would
let a model trained on, say, June data validate against April data --
which is exactly the kind of future-into-past leakage this whole
subsystem exists to prevent (CLAUDE.md non-negotiable #2, extended to
historical reconstruction by non-negotiable #8). Every fold here is an
*expanding* training window strictly before its validation window, which
mirrors how the live pipeline itself would actually accumulate data.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from cassandra.historical.challenger_negative_binomial import (
    NEGATIVE_BINOMIAL_CHALLENGER_VERSION,
    fit_negative_binomial_regression,
)
from cassandra.historical.challenger_poisson import (
    POISSON_CHALLENGER_VERSION,
    fit_poisson_regression,
)
from cassandra.historical.evaluation import EvaluationReport, evaluate_model
from cassandra.models.baseline import BaselinePoissonModel

WALK_FORWARD_MODULE_VERSION = "historical-walk-forward-0.2.0"

MIN_TRAIN_ROWS = 200  # below this an IRLS fit is unreliable -- see challenger_poisson.py

# family -> (fit function returning an object with `.model` plus
# convergence info, challenger_model_version). Both challenger families'
# fit functions share this exact shape (PoissonFitResult /
# NegativeBinomialFitResult both expose `.model`), so dispatching on it
# needs no family-specific branching inside run_walk_forward_validation
# itself -- a future third family only needs an entry here.
_CHALLENGER_FIT_FUNCTIONS: dict[str, Any] = {
    "poisson-regression": (fit_poisson_regression, POISSON_CHALLENGER_VERSION),
    "negative-binomial-regression": (fit_negative_binomial_regression, NEGATIVE_BINOMIAL_CHALLENGER_VERSION),
}


@dataclass(frozen=True)
class WalkForwardFold:
    fold_index: int
    train_n: int
    validation_n: int
    train_end_date: str
    validation_start_date: str
    validation_end_date: str
    baseline_report: EvaluationReport
    challenger_report: EvaluationReport
    challenger_converged: bool
    challenger_n_iterations: int


@dataclass(frozen=True)
class WalkForwardResult:
    walk_forward_module_version: str
    dataset_id: str
    challenger_model_version: str
    n_folds: int
    n_folds_skipped_insufficient_train_data: int
    folds: list[WalkForwardFold]
    aggregate_baseline_mae: float
    aggregate_challenger_mae: float
    # Out-of-sample tier breakdown, aggregated across every fold's held-out
    # validation rows (never a fold's own training rows) -- unlike
    # historical/evaluation.py's per-model breakdown_by_recent_k_rate_tier,
    # which a promotion decision must not treat as generalization evidence
    # when it was measured in-sample (see historical/train_final_model.py's
    # module docstring). This is the field to check before trusting any
    # claim that a challenger improves on a specific tier.
    aggregate_baseline_tier_breakdown: dict[str, dict[str, float]]
    aggregate_challenger_tier_breakdown: dict[str, dict[str, float]]


def _sorted_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: r["game_date"])


def build_expanding_folds(
    rows: list[dict[str, Any]], *, n_folds: int
) -> list[tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    """Splits time-ordered rows into `n_folds` equal-sized validation
    chunks, each paired with an *expanding* training set of every row
    strictly earlier than that chunk's earliest date -- fold 1 trains on
    rows before chunk 1, fold 2 trains on rows before chunk 2 (which
    includes chunk 1's rows, now that their true outcomes are known),
    and so on. The first fold's training set is often too small to fit
    anything on (see MIN_TRAIN_ROWS in `run_walk_forward_validation`) --
    that's expected, not a bug; there's no earlier data for it to use.
    """
    ordered = _sorted_rows(rows)
    if n_folds < 1 or not ordered:
        return []
    chunk_size = max(1, len(ordered) // n_folds)
    folds: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []
    for i in range(n_folds):
        start = i * chunk_size
        end = start + chunk_size if i < n_folds - 1 else len(ordered)
        if start >= len(ordered):
            break
        validation = ordered[start:end]
        if not validation:
            continue
        cutoff_date = validation[0]["game_date"]
        train = [r for r in ordered if r["game_date"] < cutoff_date]
        folds.append((train, validation))
    return folds


def run_walk_forward_validation(
    rows: list[dict[str, Any]], *, dataset_id: str, n_folds: int = 5, family: str = "poisson-regression"
) -> WalkForwardResult:
    """For each expanding-window fold: fits a fresh challenger (from
    `family`, see `_CHALLENGER_FIT_FUNCTIONS`) on that fold's training
    rows only, then evaluates both the challenger and the permanent,
    unmodified baseline (`k-model-0.1.0`) against that same fold's
    validation rows -- so every comparison is apples-to-apples on data
    neither model has seen. Folds with too few training rows to fit
    reliably are skipped and counted, never silently dropped."""
    if family not in _CHALLENGER_FIT_FUNCTIONS:
        raise ValueError(f"unsupported family {family!r} -- supported: {tuple(_CHALLENGER_FIT_FUNCTIONS)}")
    fit_challenger, challenger_model_version = _CHALLENGER_FIT_FUNCTIONS[family]

    folds_raw = build_expanding_folds(rows, n_folds=n_folds)
    baseline_model = BaselinePoissonModel()

    fold_results: list[WalkForwardFold] = []
    skipped = 0
    for i, (train, validation) in enumerate(folds_raw):
        if len(train) < MIN_TRAIN_ROWS:
            skipped += 1
            continue
        challenger_fit = fit_challenger(train)
        baseline_report = evaluate_model(validation, baseline_model, dataset_id=dataset_id)
        challenger_report = evaluate_model(validation, challenger_fit.model, dataset_id=dataset_id)
        fold_results.append(
            WalkForwardFold(
                fold_index=i,
                train_n=len(train),
                validation_n=len(validation),
                train_end_date=max(r["game_date"] for r in train),
                validation_start_date=min(r["game_date"] for r in validation),
                validation_end_date=max(r["game_date"] for r in validation),
                baseline_report=baseline_report,
                challenger_report=challenger_report,
                challenger_converged=challenger_fit.converged,
                challenger_n_iterations=challenger_fit.n_iterations,
            )
        )

    def _weighted_mae(reports: list[EvaluationReport]) -> float:
        total_n = sum(r.n_rows for r in reports)
        if total_n == 0:
            return 0.0
        return sum(r.mae * r.n_rows for r in reports) / total_n

    def _weighted_tier_breakdown(reports: list[EvaluationReport]) -> dict[str, dict[str, float]]:
        """Pools every fold's held-out per-tier (n, mae) into one
        out-of-sample breakdown, weighted by each fold's tier row count --
        never a fold's training rows, so a tier's apparent improvement here
        can't be an artifact of a model having been fit on that same data."""
        totals: dict[str, dict[str, float]] = {}
        for report in reports:
            for tier, stats in report.breakdown_by_recent_k_rate_tier.items():
                bucket = totals.setdefault(tier, {"n": 0.0, "abs_error_sum": 0.0})
                bucket["n"] += stats["n"]
                bucket["abs_error_sum"] += stats["mae"] * stats["n"]
        return {
            tier: {"n": bucket["n"], "mae": bucket["abs_error_sum"] / bucket["n"] if bucket["n"] else 0.0}
            for tier, bucket in totals.items()
        }

    return WalkForwardResult(
        walk_forward_module_version=WALK_FORWARD_MODULE_VERSION,
        dataset_id=dataset_id,
        challenger_model_version=challenger_model_version,
        n_folds=len(fold_results),
        n_folds_skipped_insufficient_train_data=skipped,
        folds=fold_results,
        aggregate_baseline_mae=_weighted_mae([f.baseline_report for f in fold_results]),
        aggregate_challenger_mae=_weighted_mae([f.challenger_report for f in fold_results]),
        aggregate_baseline_tier_breakdown=_weighted_tier_breakdown([f.baseline_report for f in fold_results]),
        aggregate_challenger_tier_breakdown=_weighted_tier_breakdown(
            [f.challenger_report for f in fold_results]
        ),
    )


def result_to_dict(result: WalkForwardResult) -> dict[str, Any]:
    return asdict(result)


__all__ = [
    "MIN_TRAIN_ROWS",
    "WALK_FORWARD_MODULE_VERSION",
    "WalkForwardFold",
    "WalkForwardResult",
    "build_expanding_folds",
    "result_to_dict",
    "run_walk_forward_validation",
]
