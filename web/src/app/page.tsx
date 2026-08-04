import styles from "./page.module.css";

export default function Home() {
  return (
    <main className={styles.main}>
      <div aria-hidden="true" className={styles.glow} />
      <div className={styles.content}>
        <h1 className={styles.wordmark}>CASSANDRA</h1>
        <p className={styles.tagline}>DATA. MODELS. RESULTS.</p>
        <p className={styles.status}>
          The engine is under construction. Check back soon.
        </p>
      </div>
    </main>
  );
}
