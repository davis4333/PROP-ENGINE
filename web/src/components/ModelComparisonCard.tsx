import styles from "./ModelComparisonCard.module.css";
import { readModelComparison } from "@/lib/modelComparison";

function formatMae(mae: number | null): string {
  return mae === null ? "unavailable" : mae.toFixed(4);
}

function formatPct(pct: number | null): { text: string; cls: string } {
  if (pct === null) return { text: "—", cls: styles.neutral ?? "" };
  const text = `${pct >= 0 ? "" : ""}${pct.toFixed(1)}%`;
  return {
    text,
    cls:
      pct > 0
        ? (styles.better ?? "")
        : pct < 0
          ? (styles.worse ?? "")
          : (styles.neutral ?? ""),
  };
}

/** Walk-forward comparison for one candidate artifact, both against the
 * permanent baseline and against whatever is currently ACTIVE (see
 * decision/engine.py's active-vs-candidate audit) -- reads only
 * training_metrics keys that were actually recorded; never fabricates a
 * comparison the candidate doesn't have real data for. */
export function ModelComparisonCard({
  trainingMetrics,
}: {
  trainingMetrics: Record<string, unknown>;
}) {
  const cmp = readModelComparison(trainingMetrics);
  const vsBaseline = formatPct(cmp.improvementVsBaselinePct);
  const vsActive = formatPct(cmp.improvementVsActivePct);

  if (cmp.baselineMae === null && cmp.challengerMae === null) {
    return null;
  }

  return (
    <div className={styles.row}>
      <div className={styles.item}>
        <span className={styles.label}>Candidate MAE</span>
        <span className={styles.value}>{formatMae(cmp.challengerMae)}</span>
      </div>
      <div className={styles.item}>
        <span className={styles.label}>
          vs baseline ({formatMae(cmp.baselineMae)})
        </span>
        <span className={`${styles.value} ${vsBaseline.cls}`}>
          {vsBaseline.text}
        </span>
      </div>
      <div className={styles.item}>
        <span className={styles.label}>
          vs active{" "}
          {cmp.activeMae !== null
            ? `(${formatMae(cmp.activeMae)})`
            : "(nothing active yet)"}
        </span>
        <span className={`${styles.value} ${vsActive.cls}`}>
          {vsActive.text}
        </span>
      </div>
      {cmp.nFolds !== null && (
        <div className={styles.item}>
          <span className={styles.label}>walk-forward folds</span>
          <span className={styles.value}>{cmp.nFolds}</span>
        </div>
      )}
    </div>
  );
}
