import styles from "./ProjectionsTable.module.css";
import { DecisionBadge } from "./DecisionBadge";
import { GradeBadge } from "./GradeBadge";
import { ReasonCodes } from "./ReasonCodes";
import type { ProjectionOut } from "@/lib/types";

function formatGameTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatProbability(p: number | null): string {
  return p === null ? "—" : `${(p * 100).toFixed(1)}%`;
}

export function ProjectionsTable({
  projections,
  emptyMessage,
}: {
  projections: ProjectionOut[];
  emptyMessage: string;
}) {
  if (projections.length === 0) {
    return (
      <div className={styles.wrapper}>
        <p className={styles.empty}>{emptyMessage}</p>
      </div>
    );
  }

  return (
    <div className={styles.wrapper}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Game</th>
            <th>Pitcher</th>
            <th>Line</th>
            <th>Call</th>
            <th>P(over) / P(under)</th>
            <th>Reason codes</th>
            <th>Grade</th>
          </tr>
        </thead>
        <tbody>
          {projections.map((p) => (
            <tr key={p.projection_id}>
              <td>
                {formatGameTime(p.scheduled_start_utc)}
                {p.is_late_publication && (
                  <span
                    className={styles.late}
                    title="Published after first pitch"
                  >
                    late
                  </span>
                )}
              </td>
              <td>
                <div className={styles.player}>
                  {p.player_name}
                  {p.record_label !== "LIVE" && (
                    <span
                      className={styles.recordLabel}
                      title="Not a real live pick -- excluded from official performance record"
                    >
                      {p.record_label}
                    </span>
                  )}
                </div>
                {(p.team || p.opponent) && (
                  <div className={styles.matchup}>
                    {p.team ?? "?"} vs {p.opponent ?? "?"}
                  </div>
                )}
              </td>
              <td className={styles.line}>{p.line ?? "—"}</td>
              <td>
                <DecisionBadge
                  decision={p.decision}
                  decisionStatus={p.decision_status}
                />
              </td>
              <td className={styles.probability}>
                {formatProbability(p.probability_over)} /{" "}
                {formatProbability(p.probability_under)}
              </td>
              <td>
                <ReasonCodes codes={p.reason_codes} />
              </td>
              <td>
                <GradeBadge grade={p.grade} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
