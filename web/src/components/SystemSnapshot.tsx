import styles from "./SystemSnapshot.module.css";
import type { AdminStatusResponse } from "@/lib/types";

function formatRunHours(raw: string): string {
  const hours = raw
    .split(",")
    .map((h) => parseInt(h.trim(), 10))
    .filter((h) => !Number.isNaN(h))
    .sort((a, b) => a - b);
  if (hours.length === 0) return raw;
  return hours.map((h) => `${String(h).padStart(2, "0")}:00`).join(", ");
}

/** The single "is Cassandra working, what is it doing, what does it know
 * right now" strip at the very top of Admin -- every number here comes
 * straight from AdminStatusResponse (which itself only ever reports real
 * database counts, see admin.py), never a placeholder. */
export function SystemSnapshot({ status }: { status: AdminStatusResponse }) {
  const healthy = status.blocking_issues.length === 0;

  return (
    <div className={styles.strip}>
      <div className={styles.statusRow}>
        <span
          className={`${styles.dot} ${healthy ? styles.healthy : styles.degraded}`}
        />
        <span
          className={`${styles.statusLabel} ${healthy ? styles.healthyText : styles.degradedText}`}
        >
          {healthy
            ? "HEALTHY"
            : `DEGRADED -- ${status.blocking_issues.length} issue${status.blocking_issues.length === 1 ? "" : "s"}`}
        </span>
      </div>

      <div className={styles.grid}>
        <div className={styles.stat}>
          <span className={styles.statLabel}>Today&rsquo;s Games</span>
          <span className={styles.statValue}>{status.today_games_count}</span>
          <span className={styles.statSub}>{status.today_slate_date}</span>
        </div>
        <div className={styles.stat}>
          <span className={styles.statLabel}>Qualified Plays</span>
          <span className={styles.statValue}>
            {status.today_qualified_count}
          </span>
        </div>
        <div className={styles.stat}>
          <span className={styles.statLabel}>No Plays</span>
          <span className={styles.statValue}>{status.today_no_play_count}</span>
        </div>
        <div className={styles.stat}>
          <span className={styles.statLabel}>Active Model</span>
          <span className={styles.statValue}>
            {status.active_model
              ? status.active_model.fitted_model_version
              : "Permanent baseline"}
          </span>
          <span className={styles.statSub}>{status.model_version}</span>
        </div>
        <div className={styles.stat}>
          <span className={styles.statLabel}>Pending Candidates</span>
          <span className={styles.statValue}>
            {status.pending_model_candidates.length}
          </span>
        </div>
        <div className={styles.stat}>
          <span className={styles.statLabel}>Historical Training Rows</span>
          <span className={styles.statValue}>
            {status.historical_training_rows.toLocaleString()}
          </span>
        </div>
        <div className={styles.stat}>
          <span className={styles.statLabel}>Track Record</span>
          <span className={styles.statValue}>
            {status.tracker.wins}-{status.tracker.losses}-
            {status.tracker.pushes}
          </span>
          <span className={styles.statSub}>
            {status.tracker.win_rate !== null
              ? `${(status.tracker.win_rate * 100).toFixed(1)}% win rate`
              : "no graded picks yet"}
          </span>
        </div>
        <div className={styles.stat}>
          <span className={styles.statLabel}>Auto Scheduler</span>
          <span className={styles.statValue}>
            {status.auto_scheduler_enabled ? "On" : "Off"}
          </span>
          <span className={styles.statSub}>
            {status.auto_scheduler_enabled
              ? formatRunHours(status.auto_run_hours_local)
              : "manual runs only"}
          </span>
        </div>
        <div className={styles.stat}>
          <span className={styles.statLabel}>Auto Retraining</span>
          <span className={styles.statValue}>
            {status.auto_retrain_enabled ? "On" : "Off"}
          </span>
          <span className={styles.statSub}>
            promotion always requires a human
          </span>
        </div>
      </div>
    </div>
  );
}
