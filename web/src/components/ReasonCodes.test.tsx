import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ReasonCodes } from "./ReasonCodes";

describe("ReasonCodes", () => {
  it("renders a dash when there are no codes", () => {
    render(<ReasonCodes codes={[]} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders each code as a chip with its description as a tooltip", () => {
    render(
      <ReasonCodes
        codes={[
          {
            code: "DATA_STALE",
            description:
              "The freshest data is older than the staleness threshold.",
          },
          {
            code: "LINE_SUSPENDED",
            description: "The line is marked suspended.",
          },
        ]}
      />,
    );

    const staleChip = screen.getByText("DATA_STALE");
    expect(staleChip).toBeInTheDocument();
    expect(staleChip).toHaveAttribute(
      "title",
      "The freshest data is older than the staleness threshold.",
    );
    expect(screen.getByText("LINE_SUSPENDED")).toBeInTheDocument();
  });
});
