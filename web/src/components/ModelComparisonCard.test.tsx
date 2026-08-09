import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ModelComparisonCard } from "./ModelComparisonCard";

describe("ModelComparisonCard", () => {
  it("shows real MAE and improvement figures when both baseline and active data are present", () => {
    render(
      <ModelComparisonCard
        trainingMetrics={{
          walk_forward_aggregate_baseline_mae: 2.0,
          walk_forward_aggregate_challenger_mae: 1.8,
          walk_forward_aggregate_active_mae: 1.9,
          walk_forward_n_folds: 5,
        }}
      />,
    );
    expect(screen.getByText("1.8000")).toBeInTheDocument();
    expect(screen.getByText("10.0%")).toBeInTheDocument();
    expect(screen.getByText("5.3%")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("says nothing active yet when there was no active model to compare against", () => {
    render(
      <ModelComparisonCard
        trainingMetrics={{
          walk_forward_aggregate_baseline_mae: 2.0,
          walk_forward_aggregate_challenger_mae: 1.8,
        }}
      />,
    );
    expect(screen.getByText(/nothing active yet/)).toBeInTheDocument();
  });

  it("renders nothing when the candidate has no walk-forward metrics at all", () => {
    const { container } = render(
      <ModelComparisonCard trainingMetrics={{ mae: 1.4 }} />,
    );
    expect(container.firstChild).toBeNull();
  });
});
