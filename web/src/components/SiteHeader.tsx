import Link from "next/link";
import styles from "./SiteHeader.module.css";

export function SiteHeader() {
  return (
    <header className={styles.header}>
      <Link href="/" className={styles.wordmark}>
        CASSANDRA
      </Link>
      <nav className={styles.nav}>
        <Link href="/" className={styles.link}>
          Today
        </Link>
        <Link href="/ledger" className={styles.link}>
          Ledger
        </Link>
        <Link href="/admin" className={styles.link}>
          Admin
        </Link>
      </nav>
    </header>
  );
}
