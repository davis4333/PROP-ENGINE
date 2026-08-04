import styles from "./DecisionBadge.module.css";
import type { ProjectionOut } from "@/lib/types";

const DECISION_LABEL: Record<ProjectionOut["decision"], string> = {
  OVER: "Over",
  UNDER: "Under",
  NO_PLAY: "No Play",
};

const STATUS_CLASS: Record<ProjectionOut["decision_status"], string> = {
  QUALIFIED: styles.qualified ?? "",
  UNCERTAIN: styles.uncertain ?? "",
  HELD: styles.uncertain ?? "",
  REJECTED: styles.rejected ?? "",
};

export function DecisionBadge({
  decision,
  decisionStatus,
}: {
  decision: ProjectionOut["decision"];
  decisionStatus: ProjectionOut["decision_status"];
}) {
  return (
    <span className={`${styles.badge} ${STATUS_CLASS[decisionStatus]}`}>
      {DECISION_LABEL[decision]}
      <span className={styles.status}>{decisionStatus}</span>
    </span>
  );
}
