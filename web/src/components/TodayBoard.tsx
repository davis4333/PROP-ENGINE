import styles from "./TodayBoard.module.css";
import { ProjectionCard } from "./ProjectionCard";
import type { ProjectionOut } from "@/lib/types";

/** Splits the /api/today response -- which already arrives sorted by
 * decision_status tier then probability-of-recommended-side (see
 * api/routers/today.py) -- into the three visually distinct groups the
 * page renders. Order within each group is preserved exactly as the API
 * returned it; this never re-sorts. QUALIFIED plays are real, actionable
 * calls; UNCERTAIN/HELD are worth watching but not qualified yet; REJECTED
 * are true No Plays with a reason, never mixed into the other two. */
function groupByStatus(projections: ProjectionOut[]) {
  const qualified = projections.filter(
    (p) => p.decision_status === "QUALIFIED",
  );
  const uncertain = projections.filter(
    (p) => p.decision_status === "UNCERTAIN" || p.decision_status === "HELD",
  );
  const rejected = projections.filter((p) => p.decision_status === "REJECTED");
  return { qualified, uncertain, rejected };
}

export function TodayBoard({
  projections,
  emptyMessage,
}: {
  projections: ProjectionOut[];
  emptyMessage: string;
}) {
  if (projections.length === 0) {
    return <p className={styles.empty}>{emptyMessage}</p>;
  }

  const { qualified, uncertain, rejected } = groupByStatus(projections);

  return (
    <div className={styles.board}>
      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2 className={`${styles.sectionHeading} ${styles.qualified}`}>
            Qualified Plays
          </h2>
          <span className={styles.sectionCount}>{qualified.length}</span>
        </div>
        {qualified.length === 0 ? (
          <p className={styles.sectionNote}>No qualified plays right now.</p>
        ) : (
          <div className={styles.cards}>
            {qualified.map((p) => (
              <ProjectionCard key={p.projection_id} projection={p} />
            ))}
          </div>
        )}
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2 className={`${styles.sectionHeading} ${styles.uncertain}`}>
            Watch / Uncertain
          </h2>
          <span className={styles.sectionCount}>{uncertain.length}</span>
        </div>
        {uncertain.length === 0 ? (
          <p className={styles.sectionNote}>
            Nothing on the watch list right now.
          </p>
        ) : (
          <div className={styles.cards}>
            {uncertain.map((p) => (
              <ProjectionCard key={p.projection_id} projection={p} />
            ))}
          </div>
        )}
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2 className={`${styles.sectionHeading} ${styles.rejected}`}>
            No Plays
          </h2>
          <span className={styles.sectionCount}>{rejected.length}</span>
        </div>
        {rejected.length === 0 ? (
          <p className={styles.sectionNote}>Nothing rejected on this slate.</p>
        ) : (
          <div className={styles.cards}>
            {rejected.map((p) => (
              <ProjectionCard key={p.projection_id} projection={p} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
