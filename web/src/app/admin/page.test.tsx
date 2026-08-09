import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import AdminPage from "./page";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const EMPTY_WINDOW = {
  wins: 0,
  losses: 0,
  pushes: 0,
  voids: 0,
  no_plays: 0,
  waiting: 0,
  win_rate: null,
  mean_absolute_error: null,
  projection_error_sample_size: 0,
};

const MINIMAL_ADMIN_STATUS = {
  sources: [],
  recent_runs: [],
  model_version: "k-model-0.1.0",
  decision_policy_version: "k-decision-0.2.0",
  feature_set_version: "k-features-0.1.0",
  decision_edge_threshold: 0.05,
  git_commit_sha: "deadbeef",
  active_model: null,
  pending_model_candidates: [],
  tracker: {
    wins: 0,
    losses: 0,
    pushes: 0,
    voids: 0,
    no_plays: 0,
    win_rate: null,
    tracker_started_at: "2026-08-01T00:00:00Z",
    last_reset_by: null,
  },
  scoreboard: {
    as_of: "2026-08-09T00:00:00Z",
    today: EMPTY_WINDOW,
    last_7_days: EMPTY_WINDOW,
    last_30_days: EMPTY_WINDOW,
    all_time: EMPTY_WINDOW,
  },
  blocking_issues: [],
  today_slate_date: "2026-08-09",
  today_games_count: 0,
  today_qualified_count: 0,
  today_no_play_count: 0,
  historical_training_rows: 0,
  auto_scheduler_enabled: false,
  auto_run_hours_local: "7,12,16",
  auto_retrain_enabled: false,
};

describe("AdminPage auth gate", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("skips the password gate entirely when the engine reports auth is not required (dev mode)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/health") {
          return Promise.resolve(
            jsonResponse({
              status: "ok",
              git_commit_sha: "abc",
              admin_auth_required: false,
            }),
          );
        }
        if (url === "/api/admin/status") {
          return Promise.resolve(jsonResponse(MINIMAL_ADMIN_STATUS));
        }
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    render(<AdminPage />);

    await waitFor(() => {
      expect(screen.getByText("HEALTHY")).toBeInTheDocument();
    });
    expect(screen.queryByLabelText("Admin secret")).not.toBeInTheDocument();
  });

  it("still shows the password gate when the engine reports auth IS required (production)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/health") {
          return Promise.resolve(
            jsonResponse({
              status: "ok",
              git_commit_sha: "abc",
              admin_auth_required: true,
            }),
          );
        }
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    render(<AdminPage />);

    await waitFor(() => {
      expect(screen.getByLabelText("Admin secret")).toBeInTheDocument();
    });
    expect(screen.queryByText("HEALTHY")).not.toBeInTheDocument();
  });

  it("uses a cached secret from a prior session without waiting on the health check", async () => {
    sessionStorage.setItem("cassandra_admin_secret", "a-real-secret");
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (url === "/api/admin/status") {
          const headers = init?.headers as Record<string, string> | undefined;
          expect(headers?.["X-Admin-Secret"]).toBe("a-real-secret");
          return Promise.resolve(jsonResponse(MINIMAL_ADMIN_STATUS));
        }
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    render(<AdminPage />);

    await waitFor(() => {
      expect(screen.getByText("HEALTHY")).toBeInTheDocument();
    });
  });
});
