"use client";

import { useEffect, useState } from "react";
import styles from "./page.module.css";
import { PipelineStageTracker } from "@/components/PipelineStageTracker";
import { SourceHealthTile } from "@/components/SourceHealthTile";
import {
  ApiError,
  fetchAdminStatus,
  triggerGrade,
  triggerRun,
} from "@/lib/api";
import type { AdminStatusResponse } from "@/lib/types";

const SECRET_STORAGE_KEY = "cassandra_admin_secret";

export default function AdminPage() {
  const [secret, setSecret] = useState<string | null>(null);
  const [secretInput, setSecretInput] = useState("");
  const [status, setStatus] = useState<AdminStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [slateDateInput, setSlateDateInput] = useState("");
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState(false);

  useEffect(() => {
    const stored = sessionStorage.getItem(SECRET_STORAGE_KEY);
    if (stored) setSecret(stored);
  }, []);

  useEffect(() => {
    if (!secret) return;
    setLoading(true);
    setError(null);
    fetchAdminStatus(secret)
      .then((data) => setStatus(data))
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) {
          sessionStorage.removeItem(SECRET_STORAGE_KEY);
          setSecret(null);
          setError("That admin secret was rejected. Try again.");
        } else {
          setError("Couldn't reach the Cassandra engine API.");
        }
      })
      .finally(() => setLoading(false));
  }, [secret]);

  function handleGateSubmit(e: React.FormEvent) {
    e.preventDefault();
    sessionStorage.setItem(SECRET_STORAGE_KEY, secretInput);
    setSecret(secretInput);
  }

  async function handleAction(kind: "run" | "grade") {
    if (!secret || !slateDateInput) return;
    setActionPending(true);
    setActionMessage(null);
    setActionError(null);
    try {
      if (kind === "run") {
        const result = await triggerRun(slateDateInput, secret);
        setActionMessage(
          `run_slate: ${result.entries_frozen} entries frozen, ${result.projections_published} projections published.`,
        );
      } else {
        const result = await triggerGrade(slateDateInput, secret);
        setActionMessage(
          `grade_slate: ${result.grades_written} grades written.`,
        );
      }
      const refreshed = await fetchAdminStatus(secret);
      setStatus(refreshed);
    } catch {
      setActionError(`Failed to trigger ${kind}. See engine logs for details.`);
    } finally {
      setActionPending(false);
    }
  }

  if (!secret) {
    return (
      <main className={styles.page}>
        <h1 className={styles.title}>Admin</h1>
        <p className={styles.subtitle}>
          Demo-only shared-secret gate (ADR 0011) &mdash; not production
          authentication.
        </p>
        {error && <p className={styles.error}>{error}</p>}
        <form onSubmit={handleGateSubmit} className={styles.gateForm}>
          <input
            type="password"
            placeholder="Admin secret"
            value={secretInput}
            onChange={(e) => setSecretInput(e.target.value)}
            className={styles.secretInput}
            aria-label="Admin secret"
          />
          <button type="submit" className={styles.button}>
            Enter
          </button>
        </form>
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Admin</h1>
      <p className={styles.subtitle}>
        Source health, pipeline runs, and manual run/grade triggers.
      </p>

      {loading && <p className={styles.empty}>Loading&hellip;</p>}
      {error && <p className={styles.error}>{error}</p>}

      {status && (
        <>
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Versions</h2>
            <div className={styles.versions}>
              <span>model: {status.model_version}</span>
              <span>decision policy: {status.decision_policy_version}</span>
              <span>feature set: {status.feature_set_version}</span>
              <span>edge threshold: {status.decision_edge_threshold}</span>
            </div>
          </section>

          {status.blocking_issues.length > 0 && (
            <section className={styles.section}>
              <h2 className={styles.sectionTitle}>Blocking Issues</h2>
              <div className={styles.blockingList}>
                {status.blocking_issues.map((issue) => (
                  <div key={issue} className={styles.blockingItem}>
                    {issue}
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Source Health</h2>
            {status.sources.length === 0 ? (
              <p className={styles.empty}>
                No sources have reported yet -- run a slate to populate this.
              </p>
            ) : (
              <div className={styles.tileGrid}>
                {status.sources.map((s) => (
                  <SourceHealthTile key={s.source_id} source={s} />
                ))}
              </div>
            )}
          </section>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Run / Grade a Slate</h2>
            <div className={styles.actionForm}>
              <input
                type="date"
                value={slateDateInput}
                onChange={(e) => setSlateDateInput(e.target.value)}
                className={styles.secretInput}
                aria-label="Slate date"
              />
              <button
                type="button"
                className={styles.button}
                disabled={!slateDateInput || actionPending}
                onClick={() => handleAction("run")}
              >
                Run
              </button>
              <button
                type="button"
                className={styles.button}
                disabled={!slateDateInput || actionPending}
                onClick={() => handleAction("grade")}
              >
                Grade
              </button>
            </div>
            {actionMessage && <p className={styles.success}>{actionMessage}</p>}
            {actionError && <p className={styles.error}>{actionError}</p>}
          </section>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Recent Pipeline Runs</h2>
            {status.recent_runs.length === 0 ? (
              <p className={styles.empty}>No runs yet.</p>
            ) : (
              status.recent_runs.map((run) => (
                <div key={run.run_id} className={styles.run}>
                  <div className={styles.runHeader}>
                    <span className={styles.runId}>{run.run_id}</span>
                    <span>
                      {run.slate_date} &middot; {run.status}
                    </span>
                  </div>
                  <PipelineStageTracker stages={run.stages} />
                </div>
              ))
            )}
          </section>
        </>
      )}
    </main>
  );
}
