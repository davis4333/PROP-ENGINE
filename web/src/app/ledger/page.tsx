import Link from "next/link";
import styles from "./page.module.css";
import { ProjectionsTable } from "@/components/ProjectionsTable";
import { fetchLedger } from "@/lib/api";

export default async function LedgerPage({
  searchParams,
}: {
  searchParams: Promise<{ slate_date?: string }>;
}) {
  const { slate_date: slateDate } = await searchParams;

  let ledger;
  try {
    ledger = await fetchLedger(slateDate);
  } catch {
    return (
      <main className={styles.page}>
        <h1 className={styles.title}>Results Ledger</h1>
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
        <h1 className={styles.title}>Results Ledger</h1>
        <p className={styles.subtitle}>
          Every evaluated projection and its honest grade &mdash; wins, losses,
          and pushes alike. Nothing is hidden.
        </p>
        <form action="/ledger" method="GET" className={styles.filterForm}>
          <input
            type="date"
            name="slate_date"
            defaultValue={slateDate ?? ""}
            className={styles.dateInput}
            aria-label="Filter by slate date"
          />
          <button type="submit" className={styles.button}>
            Filter
          </button>
          {slateDate && (
            <Link href="/ledger" className={styles.clearLink}>
              Clear
            </Link>
          )}
        </form>
      </div>
      <ProjectionsTable
        projections={ledger.entries}
        emptyMessage={
          slateDate
            ? "No projections found for this slate date."
            : "No projections have been published yet."
        }
      />
    </main>
  );
}
