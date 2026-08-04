import styles from "./page.module.css";
import { ProjectionsTable } from "@/components/ProjectionsTable";
import { fetchToday } from "@/lib/api";

export default async function TodayPage({
  searchParams,
}: {
  searchParams: Promise<{ slate_date?: string }>;
}) {
  const { slate_date: slateDate } = await searchParams;

  let today;
  try {
    today = await fetchToday(slateDate);
  } catch {
    return (
      <main className={styles.page}>
        <h1 className={styles.title}>Today&apos;s Slate</h1>
        <div className={styles.error}>
          Couldn&apos;t reach the Cassandra engine API. Make sure it&apos;s
          running (see README) and reachable at the configured API_BASE_URL.
        </div>
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Today&apos;s Slate</h1>
          <p className={styles.subtitle}>
            {today.slate_date} &middot; {today.games_count} game
            {today.games_count === 1 ? "" : "s"} &middot; every evaluated
            pitcher-strikeout projection, not just qualified picks.
          </p>
        </div>
        <div className={styles.summary}>
          <div className={styles.stat}>
            <span className={styles.statValue}>{today.qualified_count}</span>
            <span className={styles.statLabel}>Qualified</span>
          </div>
          <div className={styles.stat}>
            <span className={styles.statValue}>{today.no_play_count}</span>
            <span className={styles.statLabel}>No Play</span>
          </div>
          <div className={styles.stat}>
            <span className={styles.statValue}>{today.projections.length}</span>
            <span className={styles.statLabel}>Evaluated</span>
          </div>
        </div>
      </div>
      <ProjectionsTable
        projections={today.projections}
        emptyMessage="No games found for this slate date."
      />
    </main>
  );
}
