import styles from "./GradeBadge.module.css";
import type { GradeOut } from "@/lib/types";

const RESULT_CLASS: Record<GradeOut["result"], string> = {
  WIN: styles.win ?? "",
  LOSS: styles.loss ?? "",
  PUSH: styles.push ?? "",
  VOID: styles.void ?? "",
  NO_PLAY: styles.noPlay ?? "",
};

export function GradeBadge({ grade }: { grade: GradeOut | null }) {
  if (!grade) {
    return (
      <span className={`${styles.badge} ${styles.pending}`}>Not graded</span>
    );
  }
  return (
    <span className={`${styles.badge} ${RESULT_CLASS[grade.result]}`}>
      {grade.result}
    </span>
  );
}
