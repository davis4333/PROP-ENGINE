"use client";

import { useEffect, useState } from "react";
import styles from "./page.module.css";
import { ModelComparisonCard } from "@/components/ModelComparisonCard";
import { PipelineStageTracker } from "@/components/PipelineStageTracker";
import { SourceHealthTile } from "@/components/SourceHealthTile";
import { SystemSnapshot } from "@/components/SystemSnapshot";
import {
  ApiError,
  fetchAdminStatus,
  importLines,
  previewLineImport,
  resetTracker,
  triggerGrade,
  triggerRun,
} from "@/lib/api";
import { parseLineImportText } from "@/lib/lineImportParsing";
import type {
  AdminStatusResponse,
  LineImportPreviewResponse,
} from "@/lib/types";

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

  const [lineImportText, setLineImportText] = useState("");
  const [lineImportPreview, setLineImportPreview] =
    useState<LineImportPreviewResponse | null>(null);
  const [lineImportMessage, setLineImportMessage] = useState<string | null>(
    null,
  );
  const [lineImportError, setLineImportError] = useState<string | null>(null);
  const [lineImportPending, setLineImportPending] = useState(false);

  const [trackerResetPending, setTrackerResetPending] = useState(false);
  const [trackerResetError, setTrackerResetError] = useState<string | null>(
    null,
  );

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

  async function handleResetTracker() {
    if (!secret) return;
    if (
      !window.confirm(
        "Reset the win/loss tracker to 0-0? This only resets the counter -- the permanent Ledger history is never affected.",
      )
    ) {
      return;
    }
    setTrackerResetPending(true);
    setTrackerResetError(null);
    try {
      await resetTracker(secret);
      const refreshed = await fetchAdminStatus(secret);
      setStatus(refreshed);
    } catch {
      setTrackerResetError(
        "Failed to reset the tracker. See engine logs for details.",
      );
    } finally {
      setTrackerResetPending(false);
    }
  }

  async function handleLinePreview() {
    if (!secret || !slateDateInput) return;
    setLineImportPending(true);
    setLineImportMessage(null);
    setLineImportError(null);
    try {
      const entries = parseLineImportText(lineImportText);
      const result = await previewLineImport(slateDateInput, entries, secret);
      setLineImportPreview(result);
    } catch {
      setLineImportError(
        "Couldn't preview these lines. See engine logs for details.",
      );
    } finally {
      setLineImportPending(false);
    }
  }

  async function handleLineImport() {
    if (!secret || !slateDateInput) return;
    setLineImportPending(true);
    setLineImportMessage(null);
    setLineImportError(null);
    try {
      const entries = parseLineImportText(lineImportText);
      const result = await importLines(slateDateInput, entries, secret);
      setLineImportMessage(
        `Imported ${result.records_written} line(s).` +
          (result.not_imported.length > 0
            ? ` ${result.not_imported.length} not imported -- see below.`
            : ""),
      );
      setLineImportPreview(null);
    } catch {
      setLineImportError(
        "Couldn't import these lines. See engine logs for details.",
      );
    } finally {
      setLineImportPending(false);
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
          <SystemSnapshot status={status} />

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Versions</h2>
            <div className={styles.versions}>
              <span>model: {status.model_version}</span>
              <span>decision policy: {status.decision_policy_version}</span>
              <span>feature set: {status.feature_set_version}</span>
              <span>edge threshold: {status.decision_edge_threshold}</span>
              <span>deployed commit: {status.git_commit_sha ?? "unknown"}</span>
            </div>
          </section>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Active Model</h2>
            {status.active_model ? (
              <div className={styles.activeModel}>
                <span className={styles.activeModelTitle}>
                  {status.active_model.fitted_model_version}
                </span>
                <div className={styles.activeModelMeta}>
                  <span>family: {status.active_model.model_family}</span>
                  <span>
                    trained:{" "}
                    {new Date(status.active_model.trained_at).toLocaleString()}
                  </span>
                  <span>
                    activated:{" "}
                    {new Date(
                      status.active_model.activated_at,
                    ).toLocaleString()}{" "}
                    by {status.active_model.activated_by}
                  </span>
                </div>
                <div className={styles.activeModelMeta}>
                  <span>
                    dataset: {status.active_model.training_dataset_id}
                  </span>
                  {Object.entries(status.active_model.training_metrics).map(
                    ([key, value]) => (
                      <span key={key}>
                        {key}:{" "}
                        {typeof value === "number"
                          ? value.toFixed(4)
                          : String(value)}
                      </span>
                    ),
                  )}
                </div>
              </div>
            ) : (
              <p className={styles.empty}>
                Permanent baseline ({status.model_version}) -- no challenger has
                been promoted. Promote one with{" "}
                <code>cassandra promote-model</code>.
              </p>
            )}
          </section>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>
              Model Comparison
              {status.pending_model_candidates.length > 0
                ? ` -- ${status.pending_model_candidates.length} Pending`
                : ""}
            </h2>
            <p className={styles.subtitle}>
              Awaiting review -- registered by a human via{" "}
              <code>train-final-model --register</code> or automatically by the
              retraining scheduler. Nothing here is ever promoted without an
              explicit <code>cassandra promote-model</code> action.
            </p>
            {status.pending_model_candidates.length === 0 ? (
              <p className={styles.empty}>NO CHALLENGER CURRENTLY WAITING.</p>
            ) : (
              <div className={styles.pendingCandidateList}>
                {status.pending_model_candidates.map((c) => (
                  <div key={c.artifact_id} className={styles.activeModel}>
                    <span className={styles.activeModelTitle}>
                      {c.fitted_model_version}
                      <span className={styles.pendingCandidateStatus}>
                        {c.status}
                      </span>
                    </span>
                    <div className={styles.activeModelMeta}>
                      <span>family: {c.model_family}</span>
                      <span>
                        trained: {new Date(c.trained_at).toLocaleString()}
                      </span>
                      <span>registered by: {c.created_by}</span>
                      <span>dataset: {c.training_dataset_id}</span>
                    </div>
                    <ModelComparisonCard trainingMetrics={c.training_metrics} />
                    {c.notes && (
                      <div className={styles.pendingCandidateNotes}>
                        {c.notes}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Performance Tracker</h2>
            <p className={styles.subtitle}>
              A resettable win/loss counter since{" "}
              {new Date(status.tracker.tracker_started_at).toLocaleString()}
              {status.tracker.last_reset_by
                ? ` (reset by ${status.tracker.last_reset_by})`
                : " (never reset)"}
              . The Ledger page always shows the full, permanent history --
              resetting this counter never touches it.
            </p>
            <div className={styles.trackerRow}>
              <div className={styles.trackerStat}>
                <span className={styles.trackerStatValue}>
                  {status.tracker.wins}
                </span>
                <span className={styles.trackerStatLabel}>Wins</span>
              </div>
              <div className={styles.trackerStat}>
                <span className={styles.trackerStatValue}>
                  {status.tracker.losses}
                </span>
                <span className={styles.trackerStatLabel}>Losses</span>
              </div>
              <div className={styles.trackerStat}>
                <span className={styles.trackerStatValue}>
                  {status.tracker.pushes}
                </span>
                <span className={styles.trackerStatLabel}>Pushes</span>
              </div>
              <div className={styles.trackerStat}>
                <span className={styles.trackerStatValue}>
                  {status.tracker.voids}
                </span>
                <span className={styles.trackerStatLabel}>Voids</span>
              </div>
              <div className={styles.trackerStat}>
                <span className={styles.trackerStatValue}>
                  {status.tracker.win_rate !== null
                    ? `${(status.tracker.win_rate * 100).toFixed(1)}%`
                    : "—"}
                </span>
                <span className={styles.trackerStatLabel}>Win Rate</span>
              </div>
            </div>
            <button
              type="button"
              className={styles.button}
              disabled={trackerResetPending}
              onClick={handleResetTracker}
            >
              {trackerResetPending ? "Resetting…" : "Reset Tracker to 0-0"}
            </button>
            {trackerResetError && (
              <p className={styles.error}>{trackerResetError}</p>
            )}
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
            <h2 className={styles.sectionTitle}>Manual Line Import</h2>
            <p className={styles.subtitle}>
              One line per entry:{" "}
              <code>Player Name, line, over_price, under_price</code> (prices
              optional). Matched against today&rsquo;s real confirmed starters
              for the slate date selected above -- nothing is guessed for an
              unmatched or ambiguous name.
            </p>
            <textarea
              value={lineImportText}
              onChange={(e) => setLineImportText(e.target.value)}
              placeholder={"Zack Wheeler, 6.5, -115, -105\nGerrit Cole, 7.5"}
              rows={5}
              className={styles.lineImportTextarea}
              aria-label="Lines to import"
            />
            <div className={styles.actionForm}>
              <button
                type="button"
                className={styles.button}
                disabled={
                  !slateDateInput || !lineImportText.trim() || lineImportPending
                }
                onClick={handleLinePreview}
              >
                Preview
              </button>
              <button
                type="button"
                className={styles.button}
                disabled={
                  !slateDateInput || !lineImportText.trim() || lineImportPending
                }
                onClick={handleLineImport}
              >
                Import
              </button>
            </div>
            {lineImportMessage && (
              <p className={styles.success}>{lineImportMessage}</p>
            )}
            {lineImportError && (
              <p className={styles.error}>{lineImportError}</p>
            )}
            {lineImportPreview && (
              <div className={styles.lineImportPreview}>
                {lineImportPreview.matched.length > 0 && (
                  <div>
                    <strong>
                      Matched ({lineImportPreview.matched.length})
                    </strong>
                    {lineImportPreview.matched.map((m, i) => (
                      <div key={i} className={styles.lineImportRow}>
                        {m.player_name}: {m.line}
                        {m.is_possible_duplicate && (
                          <span className={styles.lineImportWarning}>
                            {" "}
                            &mdash; a line already exists for this player today
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {lineImportPreview.unmatched.length > 0 && (
                  <div>
                    <strong>
                      Not matched ({lineImportPreview.unmatched.length})
                    </strong>
                    {lineImportPreview.unmatched.map((u, i) => (
                      <div key={i} className={styles.lineImportRow}>
                        {u.player_name}: {u.reason}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
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
