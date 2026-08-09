import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ProjectionsTable } from "./ProjectionsTable";
import type { ProjectionOut } from "@/lib/types";

function makeProjection(overrides: Partial<ProjectionOut> = {}): ProjectionOut {
  return {
    projection_id: "proj-1",
    logical_key: "player-1|game-1|pitcher_strikeouts",
    version: 1,
    player_id: "player-1",
    player_name: "Yusei Kikuchi",
    team: "Blue Jays",
    opponent: "Orioles",
    game_id: "game-1",
    scheduled_start_utc: "2023-06-15T17:05:00Z",
    line: 3.5,
    projection_mean: 4.9,
    projection_sd: 2.2,
    probability_over: 0.72,
    probability_under: 0.28,
    probability_push: 0,
    decision: "OVER",
    decision_status: "QUALIFIED",
    reason_codes: [
      {
        code: "DATA_MISSING",
        description: "Umpire context unavailable (permanent stub).",
      },
    ],
    model_version: "k-model-0.1.0",
    feature_set_version: "k-features-0.1.0",
    decision_policy_version: "k-decision-0.1.0",
    reproducibility_hash: "abc123",
    published_at: "2023-06-15T16:00:00Z",
    is_late_publication: false,
    record_label: "LIVE",
    grade: null,
    edge: 0.22,
    line_source: "manual-import",
    line_observed_at: "2023-06-15T15:00:00Z",
    why: ["Projected 4.90 strikeouts vs a line of 3.5 -- 1.40 above the line."],
    risks: [],
    ...overrides,
  };
}

describe("ProjectionsTable", () => {
  it("shows the empty message when there are no projections", () => {
    render(
      <ProjectionsTable projections={[]} emptyMessage="Nothing here yet." />,
    );
    expect(screen.getByText("Nothing here yet.")).toBeInTheDocument();
  });

  it("renders a qualified projection with its call and probability", () => {
    render(
      <ProjectionsTable projections={[makeProjection()]} emptyMessage="" />,
    );

    expect(screen.getByText("Yusei Kikuchi")).toBeInTheDocument();
    expect(screen.getByText(/Blue Jays vs Orioles/)).toBeInTheDocument();
    expect(screen.getByText("3.5")).toBeInTheDocument();
    expect(screen.getByText("Over")).toBeInTheDocument();
    expect(screen.getByText("QUALIFIED")).toBeInTheDocument();
    expect(screen.getByText("72.0% / 28.0%")).toBeInTheDocument();
    expect(screen.getByText("Not graded")).toBeInTheDocument();
  });

  it("renders a NO_PLAY projection with no line", () => {
    render(
      <ProjectionsTable
        projections={[
          makeProjection({
            decision: "NO_PLAY",
            decision_status: "REJECTED",
            line: null,
            probability_over: null,
            probability_under: null,
            probability_push: null,
            reason_codes: [
              {
                code: "MARKET_CONTEXT_INCOMPLETE",
                description: "No line found.",
              },
            ],
          }),
        ]}
        emptyMessage=""
      />,
    );

    expect(screen.getByText("No Play")).toBeInTheDocument();
    expect(screen.getByText("REJECTED")).toBeInTheDocument();
    expect(screen.getByText("MARKET_CONTEXT_INCOMPLETE")).toBeInTheDocument();
  });

  it("renders a grade badge and a late-publication marker when present", () => {
    render(
      <ProjectionsTable
        projections={[
          makeProjection({
            is_late_publication: true,
            grade: {
              result: "WIN",
              actual_strikeouts: 7,
              graded_at: "2023-06-16T00:00:00Z",
            },
          }),
        ]}
        emptyMessage=""
      />,
    );

    expect(screen.getByText("WIN")).toBeInTheDocument();
    expect(screen.getByText("late")).toBeInTheDocument();
  });

  it("shows no record-label badge for a real live pick", () => {
    render(
      <ProjectionsTable projections={[makeProjection()]} emptyMessage="" />,
    );
    expect(screen.queryByText("DEMO")).not.toBeInTheDocument();
  });

  it("shows push probability for an integer line", () => {
    render(
      <ProjectionsTable
        projections={[
          makeProjection({
            line: 5,
            probability_over: 0.4,
            probability_under: 0.45,
            probability_push: 0.15,
          }),
        ]}
        emptyMessage=""
      />,
    );
    expect(screen.getByText(/P\(push\) 15\.0%/)).toBeInTheDocument();
  });

  it("does not show a push probability for a half-integer line", () => {
    render(
      <ProjectionsTable projections={[makeProjection()]} emptyMessage="" />,
    );
    expect(screen.queryByText(/P\(push\)/)).not.toBeInTheDocument();
  });

  it("badges a non-LIVE record so it can never be mistaken for a real pick", () => {
    render(
      <ProjectionsTable
        projections={[makeProjection({ record_label: "DEMO" })]}
        emptyMessage=""
      />,
    );
    expect(screen.getByText("DEMO")).toBeInTheDocument();
  });
});
