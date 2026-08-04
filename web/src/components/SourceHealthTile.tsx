import styles from "./SourceHealthTile.module.css";
import type { SourceHealthOut } from "@/lib/types";

function statusClass(status: string | null): string {
  if (status === "ok") return styles.ok ?? "";
  if (status === "unavailable") return styles.unavailable ?? "";
  return styles.unknown ?? "";
}

export function SourceHealthTile({ source }: { source: SourceHealthOut }) {
  return (
    <div className={`${styles.tile} ${statusClass(source.last_status)}`}>
      <div className={styles.name}>
        <span className={styles.dot} aria-hidden="true" />
        {source.source_id}
      </div>
      <div className={styles.row}>
        <span>{source.last_status ?? "never run"}</span>
        {source.consecutive_failures > 0 && (
          <span className={styles.failures}>
            {source.consecutive_failures}x fail
          </span>
        )}
      </div>
    </div>
  );
}
