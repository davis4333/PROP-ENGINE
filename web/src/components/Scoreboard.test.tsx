import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Scoreboard } from "./Scoreboard";
import type { ScoreboardOut, ScoreboardWindowOut } from "@/lib/types";

function makeWindow(
  overrides: Partial<ScoreboardWindowOut> = {},
): ScoreboardWindowOut {
  return {
    wins: 0,
    losses: 0,
    pushes: 0,
    voids: 0,
    no_plays: 0,
    waiting: 0,
    win_rate: null,
    mean_absolute_error: null,
    projection_error_sample_size: 0,
    ...overrides,
  };
}

function makeScoreboard(overrides: Partial<ScoreboardOut> = {}): ScoreboardOut {
  return {
    as_of: "2026-08-09T12:00:00Z",
    today: makeWindow(),
    last_7_days: makeWindow(),
    last_30_days: makeWindow(),
    all_time: makeWindow(),
    ...overrides,
  };
}

describe("Scoreboard", () => {
  it("renders all four windows with real record labels", () => {
    render(<Scoreboard scoreboard={makeScoreboard()} />);
    expect(screen.getByText("Today")).toBeInTheDocument();
    expect(screen.getByText("Last 7 Days")).toBeInTheDocument();
    expect(screen.getByText("Last 30 Days")).toBeInTheDocument();
    expect(screen.getByText("All-Time")).toBeInTheDocument();
  });

  it("shows the win-loss-push record and win rate for a window with real data", () => {
    render(
      <Scoreboard
        scoreboard={makeScoreboard({
          today: makeWindow({ wins: 3, losses: 1, pushes: 0, win_rate: 0.75 }),
        })}
      />,
    );
    expect(screen.getByText("3-1-0")).toBeInTheDocument();
    expect(screen.getByText("75.0% win rate")).toBeInTheDocument();
  });

  it("says there are no decided picks yet rather than a fake 0%", () => {
    render(
      <Scoreboard
        scoreboard={makeScoreboard({ today: makeWindow({ win_rate: null }) })}
      />,
    );
    expect(screen.getAllByText("no decided picks yet").length).toBeGreaterThan(
      0,
    );
  });

  it("shows real projection error, and a plain no-data message when none exists", () => {
    const { container } = render(
      <Scoreboard
        scoreboard={makeScoreboard({
          today: makeWindow({
            mean_absolute_error: 1.86,
            projection_error_sample_size: 12,
          }),
        })}
      />,
    );
    expect(container.textContent).toContain(
      "off by 1.86 strikeouts on average (12 graded)",
    );
    expect(container.textContent).toContain(
      "no graded picks with a known outcome yet",
    );
  });

  it("surfaces the waiting count distinctly from no-plays and voids", () => {
    const { container } = render(
      <Scoreboard
        scoreboard={makeScoreboard({
          today: makeWindow({ waiting: 4, no_plays: 2, voids: 1 }),
        })}
      />,
    );
    expect(container.textContent).toContain("4 waiting on a final result");
    expect(container.textContent).toContain("2 No Plays, 1 voided");
  });
});
