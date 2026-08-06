import styles from "./SourceHealthTile.module.css";
import type { SourceHealthOut } from "@/lib/types";

// Mirrors engine/src/cassandra/db/models/sources.py's SOURCE_HEALTH_STATES.
// last_status is a free-text column, not a typed enum end-to-end, so this
// is the one place the frontend needs to stay in sync with that vocabulary.
function statusClass(status: string | null): string {
  switch (status) {
    case "HEALTHY":
      return styles.healthy ?? "";
    case "PENDING":
      return styles.pending ?? "";
    case "DEGRADED":
      return styles.degraded ?? "";
    case "QUOTA_LIMITED":
      return styles.quotaLimited ?? "";
    case "DISABLED":
      return styles.disabled ?? "";
    case "FAILED":
      return styles.failed ?? "";
    default:
      return styles.unknown ?? "";
  }
}

// Plain-English detail + recommended action, per the Admin operating-view
// requirement -- last_status alone ("DEGRADED") isn't self-explanatory to
// someone who isn't reading the source code.
function statusDetail(status: string | null): string | null {
  switch (status) {
    case "PENDING":
      return "Expected -- data isn't posted/available yet, will retry automatically.";
    case "DEGRADED":
      return "Recent fetch errors, not yet alarming. Watch for escalation.";
    case "QUOTA_LIMITED":
      return "Vendor rate/quota limit hit. Will resume once quota allows.";
    case "DISABLED":
      return "Permanently unavailable by design -- no action needed.";
    case "FAILED":
      return "Repeated real fetch failures. Needs investigation.";
    default:
      return null;
  }
}

export function SourceHealthTile({ source }: { source: SourceHealthOut }) {
  const detail = statusDetail(source.last_status);
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
      {detail && <div className={styles.detail}>{detail}</div>}
    </div>
  );
}
