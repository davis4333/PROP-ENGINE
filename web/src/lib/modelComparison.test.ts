import { describe, expect, it } from "vitest";
import { readModelComparison } from "./modelComparison";

describe("readModelComparison", () => {
  it("computes real improvement percentages when both MAEs are present", () => {
    const result = readModelComparison({
      walk_forward_aggregate_baseline_mae: 2.0,
      walk_forward_aggregate_challenger_mae: 1.8,
      walk_forward_aggregate_active_mae: 1.9,
      walk_forward_n_folds: 5,
    });
    expect(result.baselineMae).toBe(2.0);
    expect(result.challengerMae).toBe(1.8);
    expect(result.activeMae).toBe(1.9);
    expect(result.improvementVsBaselinePct).toBeCloseTo(10.0);
    expect(result.improvementVsActivePct).toBeCloseTo(5.263, 2);
    expect(result.nFolds).toBe(5);
  });

  it("never invents an active-model comparison when nothing was ever active", () => {
    const result = readModelComparison({
      walk_forward_aggregate_baseline_mae: 2.0,
      walk_forward_aggregate_challenger_mae: 1.8,
      walk_forward_aggregate_active_mae: null,
    });
    expect(result.activeMae).toBeNull();
    expect(result.improvementVsActivePct).toBeNull();
    expect(result.improvementVsBaselinePct).toBeCloseTo(10.0);
  });

  it("returns all nulls when training_metrics has none of the expected keys", () => {
    const result = readModelComparison({ mae: 1.4 });
    expect(result.baselineMae).toBeNull();
    expect(result.challengerMae).toBeNull();
    expect(result.activeMae).toBeNull();
    expect(result.improvementVsBaselinePct).toBeNull();
    expect(result.improvementVsActivePct).toBeNull();
  });

  it("a negative improvement means the candidate is actually worse, not clamped to zero", () => {
    const result = readModelComparison({
      walk_forward_aggregate_baseline_mae: 1.5,
      walk_forward_aggregate_challenger_mae: 1.5,
      walk_forward_aggregate_active_mae: 1.2,
    });
    expect(result.improvementVsActivePct).toBeLessThan(0);
  });
});
