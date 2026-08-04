import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DecisionBadge } from "./DecisionBadge";

describe("DecisionBadge", () => {
  it("renders the human label and raw status", () => {
    render(<DecisionBadge decision="OVER" decisionStatus="QUALIFIED" />);
    expect(screen.getByText("Over")).toBeInTheDocument();
    expect(screen.getByText("QUALIFIED")).toBeInTheDocument();
  });

  it("renders No Play for NO_PLAY decisions", () => {
    render(<DecisionBadge decision="NO_PLAY" decisionStatus="REJECTED" />);
    expect(screen.getByText("No Play")).toBeInTheDocument();
    expect(screen.getByText("REJECTED")).toBeInTheDocument();
  });
});
