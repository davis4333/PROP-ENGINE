import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { TodayBoard } from "./TodayBoard";
import type { ProjectionOut } from "@/lib/types";

function makeProjection(overrides: Partial<ProjectionOut> = {}): ProjectionOut {
  return {
    projection_id: "proj-1",
    logical_key: "player-1|game-1|pitcher_strikeouts",
    version: 1,
    player_id: "player-1",
    player_name: "Test Pitcher",
    team: "Home",
    opponent: "Away",
    game_id: "game-1",
    scheduled_start_utc: "2023-06-15T17:05:00Z",
    line: 5.5,
    projection_mean: 6.8,
    projection_sd: 2.1,
    probability_over: 0.68,
    probability_under: 0.32,
    probability_push: 0,
    decision: "OVER",
    decision_status: "QUALIFIED",
    reason_codes: [],
    model_version: "k-model-0.1.0",
    feature_set_version: "k-features-0.1.0",
    decision_policy_version: "k-decision-0.2.0",
    reproducibility_hash: "abc123",
    published_at: "2023-06-15T16:00:00Z",
    is_late_publication: false,
    record_label: "LIVE",
    grade: null,
    edge: 0.18,
    line_source: "manual-import",
    line_observed_at: "2023-06-15T15:00:00Z",
    why: ["Projected 6.80 strikeouts vs a line of 5.5 -- 1.30 above the line."],
    risks: [],
    ...overrides,
  };
}

describe("TodayBoard", () => {
  it("shows the empty message when there are no projections at all", () => {
    render(<TodayBoard projections={[]} emptyMessage="Nothing here yet." />);
    expect(screen.getByText("Nothing here yet.")).toBeInTheDocument();
  });

  it("separates QUALIFIED, UNCERTAIN, and REJECTED into distinct sections", () => {
    const qualified = makeProjection({
      projection_id: "q-1",
      decision: "OVER",
      decision_status: "QUALIFIED",
    });
    const uncertain = makeProjection({
      projection_id: "u-1",
      player_name: "Uncertain Pitcher",
      decision: "NO_PLAY",
      decision_status: "UNCERTAIN",
      why: [],
      risks: [
        "The model's edge over the neutral decision baseline is below the gate.",
      ],
    });
    const rejected = makeProjection({
      projection_id: "r-1",
      player_name: "Rejected Pitcher",
      decision: "NO_PLAY",
      decision_status: "REJECTED",
      line: null,
      why: [],
      risks: [
        "Line/market context needed to evaluate this prop is incomplete.",
      ],
    });

    render(
      <TodayBoard
        projections={[qualified, uncertain, rejected]}
        emptyMessage="unused"
      />,
    );

    expect(screen.getByText("Qualified Plays")).toBeInTheDocument();
    expect(screen.getByText("Watch / Uncertain")).toBeInTheDocument();
    expect(screen.getByText("No Plays")).toBeInTheDocument();
    expect(screen.getByText("Test Pitcher")).toBeInTheDocument();
    expect(screen.getByText("Uncertain Pitcher")).toBeInTheDocument();
    expect(screen.getByText("Rejected Pitcher")).toBeInTheDocument();
  });

  it("never puts a REJECTED row's why-bullets in the qualified section's tone", () => {
    const rejected = makeProjection({
      projection_id: "r-2",
      decision: "NO_PLAY",
      decision_status: "REJECTED",
      line: null,
      why: [],
      risks: [
        "Line/market context needed to evaluate this prop is incomplete.",
      ],
    });
    render(<TodayBoard projections={[rejected]} emptyMessage="unused" />);

    expect(screen.getByText("Why this is a No Play")).toBeInTheDocument();
    expect(
      screen.queryByText("Why Cassandra likes this"),
    ).not.toBeInTheDocument();
  });
});
