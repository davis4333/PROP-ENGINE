import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SystemSnapshot } from "./SystemSnapshot";
import type { AdminStatusResponse } from "@/lib/types";

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

function makeStatus(
  overrides: Partial<AdminStatusResponse> = {},
): AdminStatusResponse {
  return {
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
      wins: 3,
      losses: 2,
      pushes: 0,
      voids: 0,
      no_plays: 5,
      win_rate: 0.6,
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
    today_games_count: 12,
    today_qualified_count: 4,
    today_no_play_count: 6,
    historical_training_rows: 14578,
    auto_scheduler_enabled: true,
    auto_run_hours_local: "7,12,16",
    auto_retrain_enabled: false,
    ...overrides,
  };
}

describe("SystemSnapshot", () => {
  it("shows HEALTHY with no blocking issues", () => {
    render(<SystemSnapshot status={makeStatus()} />);
    expect(screen.getByText("HEALTHY")).toBeInTheDocument();
  });

  it("shows DEGRADED with the real blocking-issue count when any exist", () => {
    render(
      <SystemSnapshot
        status={makeStatus({
          blocking_issues: ["Source x failed 3 times in a row"],
        })}
      />,
    );
    expect(screen.getByText(/DEGRADED -- 1 issue/)).toBeInTheDocument();
  });

  it("renders real counts, never placeholders", () => {
    render(<SystemSnapshot status={makeStatus()} />);
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument();
    expect(screen.getByText("14,578")).toBeInTheDocument();
    expect(screen.getByText("3-2-0")).toBeInTheDocument();
    expect(screen.getByText("Permanent baseline")).toBeInTheDocument();
  });

  it("shows the active model's fitted version when one is promoted", () => {
    render(
      <SystemSnapshot
        status={makeStatus({
          active_model: {
            artifact_id: "artifact_1",
            model_family: "poisson-regression",
            fitted_model_version:
              "poisson-regression-challenger-0.1.0+artifact_1",
            trained_at: "2026-08-01T00:00:00Z",
            training_dataset_id: "ds_1",
            training_metrics: {},
            activated_at: "2026-08-02T00:00:00Z",
            activated_by: "tyler",
          },
        })}
      />,
    );
    expect(
      screen.getByText("poisson-regression-challenger-0.1.0+artifact_1"),
    ).toBeInTheDocument();
  });

  it("formats configured auto-run hours for a human, only when the scheduler is on", () => {
    render(
      <SystemSnapshot status={makeStatus({ auto_scheduler_enabled: true })} />,
    );
    expect(screen.getByText("07:00, 12:00, 16:00")).toBeInTheDocument();

    render(
      <SystemSnapshot status={makeStatus({ auto_scheduler_enabled: false })} />,
    );
    expect(screen.getByText("manual runs only")).toBeInTheDocument();
  });
});
