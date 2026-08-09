import styles from "./DataQualityBadge.module.css";
import { DATA_QUALITY_LABEL, dataQualityTier } from "@/lib/quality";
import type { ProjectionOut } from "@/lib/types";

const TIER_CLASS: Record<ReturnType<typeof dataQualityTier>, string> = {
  COMPLETE: styles.complete ?? "",
  GOOD: styles.good ?? "",
  LIMITED: styles.limited ?? "",
  POOR: styles.poor ?? "",
};

export function DataQualityBadge({
  projection,
}: {
  projection: ProjectionOut;
}) {
  const tier = dataQualityTier(projection);
  return (
    <span className={`${styles.badge} ${TIER_CLASS[tier]}`}>
      {DATA_QUALITY_LABEL[tier]}
    </span>
  );
}
