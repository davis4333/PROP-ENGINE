import styles from "./ProjectionCard.module.css";
import { DataQualityBadge } from "./DataQualityBadge";
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

function formatEdge(edge: number | null): string {
  if (edge === null) return "—";
  const points = (edge * 100).toFixed(1);
  return edge >= 0 ? `+${points} pts` : `${points} pts`;
}

function formatLineAge(iso: string | null): string {
  if (iso === null) return "—";
  const ageMs = Date.now() - new Date(iso).getTime();
  const ageMinutes = Math.round(ageMs / 60000);
  if (ageMinutes < 1) return "just now";
  if (ageMinutes < 60) return `${ageMinutes}m ago`;
  const hours = Math.round(ageMinutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/** The probability of the side Cassandra actually recommended -- OVER and
 * UNDER treated equally, never a raw projected total. Matches
 * api/routers/today.py's own ranking key (max(P(over), P(under))), so
 * what's displayed here is exactly what the list is sorted by. */
function recommendedProbability(p: ProjectionOut): number | null {
  if (p.decision === "OVER") return p.probability_over;
  if (p.decision === "UNDER") return p.probability_under;
  return null;
}

export function ProjectionCard({
  projection: p,
}: {
  projection: ProjectionOut;
}) {
  const cardClass =
    p.decision_status === "QUALIFIED"
      ? styles.qualified
      : p.decision_status === "REJECTED"
        ? styles.rejected
        : styles.uncertain;
  const recommendedProb = recommendedProbability(p);

  return (
    <div className={`${styles.card} ${cardClass}`}>
      <div className={styles.top}>
        <div className={styles.identity}>
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
          <div className={styles.matchup}>
            {p.team ?? "?"} vs {p.opponent ?? "?"} &middot;{" "}
            {formatGameTime(p.scheduled_start_utc)}
            {p.is_late_publication && " (late)"}
          </div>
        </div>
        <DecisionBadge
          decision={p.decision}
          decisionStatus={p.decision_status}
        />
      </div>

      <div className={styles.numbers}>
        <div className={styles.stat}>
          <span className={styles.statLabel}>Market line</span>
          <span className={styles.statValue}>{p.line ?? "No line"}</span>
        </div>
        <div className={styles.stat}>
          <span className={styles.statLabel}>Projection</span>
          <span className={styles.statValue}>
            {p.projection_mean !== null ? p.projection_mean.toFixed(2) : "—"}
          </span>
        </div>
        <div className={styles.stat}>
          <span className={styles.statLabel}>
            P(
            {p.decision === "NO_PLAY"
              ? "recommended"
              : p.decision.toLowerCase()}
            )
          </span>
          <span className={styles.statValue}>
            {formatProbability(recommendedProb)}
          </span>
        </div>
        {p.probability_push !== null && p.probability_push > 0 && (
          <div className={styles.stat}>
            <span className={styles.statLabel}>P(push)</span>
            <span className={styles.statValue}>
              {formatProbability(p.probability_push)}
            </span>
          </div>
        )}
        <div className={styles.stat}>
          <span className={styles.statLabel}>Edge</span>
          <span className={styles.statValue}>{formatEdge(p.edge)}</span>
        </div>
        <div className={styles.stat}>
          <span className={styles.statLabel}>Data quality</span>
          <span className={styles.statValue}>
            <DataQualityBadge projection={p} />
          </span>
        </div>
        <div className={styles.stat}>
          <span className={styles.statLabel}>Grade</span>
          <span className={styles.statValue}>
            <GradeBadge grade={p.grade} />
          </span>
        </div>
      </div>

      {p.why.length > 0 && (
        <div className={styles.section}>
          <span className={styles.sectionTitle}>Why Cassandra likes this</span>
          <ul className={styles.why}>
            {p.why.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {p.risks.length > 0 && (
        <div className={styles.section}>
          <span className={styles.sectionTitle}>
            {p.decision === "NO_PLAY"
              ? "Why this is a No Play"
              : "Risks to know about"}
          </span>
          <ul className={styles.risks}>
            {p.risks.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      <div className={styles.meta}>
        <span>
          Line: {p.line_source ?? "unavailable"}
          {p.line_observed_at && ` (${formatLineAge(p.line_observed_at)})`}
        </span>
        <span>Model: {p.model_version ?? "unknown"}</span>
        <span>
          Evaluated: {formatGameTime(p.published_at ?? p.scheduled_start_utc)}
        </span>
      </div>

      <ReasonCodes codes={p.reason_codes} />
    </div>
  );
}
