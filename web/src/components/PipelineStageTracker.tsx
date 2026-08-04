import styles from "./PipelineStageTracker.module.css";
import { PIPELINE_STAGES } from "@/lib/api";
import type { PipelineStageOut } from "@/lib/types";

const STATUS_CLASS: Record<PipelineStageOut["status"], string> = {
  succeeded: styles.succeeded ?? "",
  failed: styles.failed ?? "",
  running: styles.running ?? "",
  pending: styles.pending ?? "",
  skipped: styles.skipped ?? "",
};

export function PipelineStageTracker({
  stages,
}: {
  stages: PipelineStageOut[];
}) {
  const byStage = new Map(stages.map((s) => [s.stage, s]));

  return (
    <div className={styles.tracker}>
      {PIPELINE_STAGES.map((stageName) => {
        const stage = byStage.get(stageName);
        const status = stage?.status ?? "pending";
        return (
          <div
            key={stageName}
            className={`${styles.stage} ${STATUS_CLASS[status]}`}
            title={stage?.detail ?? ""}
          >
            <span className={styles.stageName}>{stageName}</span>
            <span className={styles.stageStatus}>{status}</span>
          </div>
        );
      })}
    </div>
  );
}
