import type { ProjectionOut } from "@/lib/types";

export type DataQualityTier = "COMPLETE" | "GOOD" | "LIMITED" | "POOR";

// A real, defined formula over the same reason_codes/decision_status the
// engine already computed -- never a fabricated percentage. DATA_MISSING
// is excluded from every tier check below when it's the umpire stub's
// permanent, expected, never-blocking absence (see decision/engine.py's
// QUALITY_RISK_CODES docstring and adapters/umpire_stub.py) -- the only
// way to tell that apart from a real DATA_MISSING (e.g. no probable
// pitcher at all) from reason_codes alone is that the umpire one never
// prevents QUALIFIED, so it's the only DATA_MISSING a QUALIFIED/UNCERTAIN
// row can ever carry.
const ALWAYS_EXPECTED = new Set(["DATA_MISSING"]);
const COMMON_PRE_LINEUP = new Set(["LINEUP_UNCONFIRMED"]);

export function dataQualityTier(projection: ProjectionOut): DataQualityTier {
  const codes = new Set(projection.reason_codes.map((c) => c.code));

  if (projection.decision_status === "REJECTED") {
    return "POOR";
  }

  const remaining = [...codes].filter((c) => !ALWAYS_EXPECTED.has(c));
  if (remaining.length === 0) {
    return "COMPLETE";
  }
  if (remaining.every((c) => COMMON_PRE_LINEUP.has(c))) {
    return "GOOD";
  }
  return "LIMITED";
}

export const DATA_QUALITY_LABEL: Record<DataQualityTier, string> = {
  COMPLETE: "Complete",
  GOOD: "Good",
  LIMITED: "Limited",
  POOR: "Poor",
};
