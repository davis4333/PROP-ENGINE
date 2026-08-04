import styles from "./ReasonCodes.module.css";
import type { ReasonCodeOut } from "@/lib/types";

export function ReasonCodes({ codes }: { codes: ReasonCodeOut[] }) {
  if (codes.length === 0) {
    return <span className={styles.empty}>&mdash;</span>;
  }
  return (
    <span className={styles.list}>
      {codes.map((c) => (
        <span key={c.code} className={styles.chip} title={c.description}>
          {c.code}
        </span>
      ))}
    </span>
  );
}
