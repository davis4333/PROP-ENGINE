import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PipelineStageTracker } from "./PipelineStageTracker";

describe("PipelineStageTracker", () => {
  it("renders all 7 canonical stages even when only some are reported", () => {
    render(
      <PipelineStageTracker
        stages={[
          {
            stage: "INGEST",
            status: "succeeded",
            started_at: null,
            finished_at: null,
            detail: null,
          },
          {
            stage: "FREEZE",
            status: "failed",
            started_at: null,
            finished_at: null,
            detail: "boom",
          },
        ]}
      />,
    );

    for (const stage of [
      "INGEST",
      "VALIDATE",
      "FREEZE",
      "PROJECT",
      "REVIEW",
      "PUBLISH",
      "GRADE",
    ]) {
      expect(screen.getByText(stage)).toBeInTheDocument();
    }
    expect(screen.getByText("succeeded")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
    // stages never reported for this run default to pending, not missing/crashing
    expect(screen.getAllByText("pending").length).toBeGreaterThan(0);
  });
});
