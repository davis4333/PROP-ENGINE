import { describe, expect, it } from "vitest";
import { dataQualityTier } from "./quality";
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
    why: [],
    risks: [],
    ...overrides,
  };
}

describe("dataQualityTier", () => {
  it("is COMPLETE with no reason codes", () => {
    expect(dataQualityTier(makeProjection({ reason_codes: [] }))).toBe(
      "COMPLETE",
    );
  });

  it("is COMPLETE when only the permanent umpire stub gap is present", () => {
    const p = makeProjection({
      reason_codes: [
        { code: "DATA_MISSING", description: "Umpire unavailable." },
      ],
    });
    expect(dataQualityTier(p)).toBe("COMPLETE");
  });

  it("is GOOD when only the lineup is still unconfirmed", () => {
    const p = makeProjection({
      reason_codes: [
        { code: "LINEUP_UNCONFIRMED", description: "Lineup not confirmed." },
      ],
    });
    expect(dataQualityTier(p)).toBe("GOOD");
  });

  it("is LIMITED when a real risk code is present on a still-QUALIFIED/UNCERTAIN row", () => {
    const p = makeProjection({
      decision_status: "UNCERTAIN",
      reason_codes: [{ code: "DATA_STALE", description: "Stale." }],
    });
    expect(dataQualityTier(p)).toBe("LIMITED");
  });

  it("is POOR whenever the row was REJECTED, regardless of which codes are present", () => {
    const p = makeProjection({
      decision: "NO_PLAY",
      decision_status: "REJECTED",
      reason_codes: [
        { code: "MARKET_CONTEXT_INCOMPLETE", description: "No line." },
      ],
    });
    expect(dataQualityTier(p)).toBe("POOR");
  });
});
