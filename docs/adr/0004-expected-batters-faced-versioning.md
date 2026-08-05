# ADR 0004 — Expected batters faced: versioned, separate module, explicit fallback

**Status:** Decided and implemented (`features/expected_bf.py`)

## Decision

Expected batters faced (workload proxy feeding the baseline model, ADR
0003) is computed by its own versioned function
(`features/expected_bf.py`, e.g. `expected_bf_v1`), not inlined into the
model. It gets its own version string (independent of
`feature_set_version`) so its fallback logic can change without forcing a
full feature-set or model-version bump.

Explicit fallback chain (highest-quality signal first):
1. Weighted average of batters faced over the pitcher's last N starts
   (decay-weighted, same half-life family as recent K-rate).
2. Season-to-date average batters faced, if fewer than N starts available.
3. Career average batters faced for pitchers in a similar role
   (starter/reliever), if season sample is too small.
4. A role-based league default (e.g. league-average starter BF), only if
   no pitcher-specific history exists at all — this case must set a
   `role_stability_flag`/reason code so the decision engine can see the
   projection is running on a weak workload estimate, not silently treat
   it as normal.

Each fallback tier used is recorded alongside the computed value so it's
visible in the feature record which tier fired, not just the final number.

## Status

Implemented. `features/expected_bf.py` implements the fallback chain
above with `expected_bf_version`/`expected_bf_tier` fields, referenced
by `features/registry.py` — verified by an independent architecture
review.
