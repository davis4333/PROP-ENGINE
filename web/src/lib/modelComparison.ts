/** Reads the walk-forward comparison keys orchestration/
 * retraining_scheduler.py and historical/train_final_model.py write into
 * a candidate's training_metrics (see their own docstrings for the exact
 * keys) and turns them into plain-English improvement figures -- never
 * invents a number when a key wasn't actually recorded for a given
 * artifact (e.g. a hand-registered candidate that skipped walk-forward
 * validation, or one trained before an active model ever existed). */

export interface ModelComparison {
  baselineMae: number | null;
  challengerMae: number | null;
  activeMae: number | null;
  improvementVsBaselinePct: number | null;
  improvementVsActivePct: number | null;
  nFolds: number | null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function improvementPct(from: number | null, to: number | null): number | null {
  if (from === null || to === null || from === 0) return null;
  return ((from - to) / from) * 100;
}

export function readModelComparison(
  trainingMetrics: Record<string, unknown>,
): ModelComparison {
  const baselineMae = asNumber(
    trainingMetrics["walk_forward_aggregate_baseline_mae"],
  );
  const challengerMae = asNumber(
    trainingMetrics["walk_forward_aggregate_challenger_mae"],
  );
  const activeMae = asNumber(
    trainingMetrics["walk_forward_aggregate_active_mae"],
  );
  const nFolds = asNumber(trainingMetrics["walk_forward_n_folds"]);

  return {
    baselineMae,
    challengerMae,
    activeMae,
    improvementVsBaselinePct: improvementPct(baselineMae, challengerMae),
    improvementVsActivePct: improvementPct(activeMae, challengerMae),
    nFolds,
  };
}
