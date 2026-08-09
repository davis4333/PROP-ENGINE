import styles from "./Scoreboard.module.css";
import type { ScoreboardOut, ScoreboardWindowOut } from "@/lib/types";

function formatWinRate(rate: number | null): string {
  return rate === null
    ? "no decided picks yet"
    : `${(rate * 100).toFixed(1)}% win rate`;
}

function formatError(window: ScoreboardWindowOut): string {
  if (window.mean_absolute_error === null)
    return "no graded picks with a known outcome yet";
  return `off by ${window.mean_absolute_error.toFixed(2)} strikeouts on average (${window.projection_error_sample_size} graded)`;
}

function WindowCard({
  label,
  window,
}: {
  label: string;
  window: ScoreboardWindowOut;
}) {
  return (
    <div className={styles.card}>
      <span className={styles.windowLabel}>{label}</span>
      <span className={styles.record}>
        {window.wins}-{window.losses}-{window.pushes}
      </span>
      <span className={styles.recordSub}>{formatWinRate(window.win_rate)}</span>
      <div className={styles.rows}>
        <span>
          <strong>{window.waiting}</strong> waiting on a final result
        </span>
        <span>
          <strong>{window.no_plays}</strong> No Plays,{" "}
          <strong>{window.voids}</strong> voided
        </span>
        <span>
          Cassandra&rsquo;s projections have been {formatError(window)}.
        </span>
      </div>
    </div>
  );
}

/** The permanent, un-resettable, strictly LIVE-only track record --
 * distinct from the resettable Performance Tracker counter above it.
 * Never mixes in DEMO/BACKTEST/PAPER/SHADOW results (grading/
 * scoreboard.py's own guarantee); every number here traces back to a
 * real grades row. */
export function Scoreboard({ scoreboard }: { scoreboard: ScoreboardOut }) {
  return (
    <div className={styles.grid}>
      <WindowCard label="Today" window={scoreboard.today} />
      <WindowCard label="Last 7 Days" window={scoreboard.last_7_days} />
      <WindowCard label="Last 30 Days" window={scoreboard.last_30_days} />
      <WindowCard label="All-Time" window={scoreboard.all_time} />
    </div>
  );
}
