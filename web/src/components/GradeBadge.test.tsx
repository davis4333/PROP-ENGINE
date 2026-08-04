import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { GradeBadge } from "./GradeBadge";

describe("GradeBadge", () => {
  it("shows 'Not graded' when grade is null", () => {
    render(<GradeBadge grade={null} />);
    expect(screen.getByText("Not graded")).toBeInTheDocument();
  });

  it.each([
    ["WIN", 7],
    ["LOSS", 2],
    ["PUSH", 5],
    ["VOID", null],
    ["NO_PLAY", null],
  ] as const)("renders %s", (result, actual) => {
    render(
      <GradeBadge
        grade={{
          result,
          actual_strikeouts: actual,
          graded_at: "2023-06-16T00:00:00Z",
        }}
      />,
    );
    expect(screen.getByText(result)).toBeInTheDocument();
  });
});
