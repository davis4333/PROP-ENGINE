"""The feature-set registry: documents exactly what
`feature_values.features` (a JSONB blob, see db/models/features.py) is
expected to contain for `FEATURE_SET_VERSION`. A JSONB blob rather than a
column-per-feature table is deliberate while the model family is still
open (handbook non-negotiable #7) -- this registry is what keeps that
flexible without becoming undocumented.

Bump `FEATURE_SET_VERSION` whenever a feature is added, removed, or
redefined -- published projections pin whatever version produced them
permanently (ADR 0010), so this is the only place "what does
feature_set_version X mean" should ever need to be answered.
"""

from __future__ import annotations

FEATURE_SET_VERSION = "k-features-0.1.0"

FEATURE_FIELDS: dict[str, str] = {
    "expected_bf": "Expected batters faced this start (see features/expected_bf.py).",
    "expected_bf_tier": (
        "Which fallback tier produced expected_bf: recent_weighted | season_average | league_default."
    ),
    "expected_bf_version": "Independent version of the expected-BF calculation (ADR 0004).",
    "expected_bf_starts_used": "How many prior starts fed expected_bf.",
    "recent_k_rate": (
        "Decay-weighted strikeouts-per-batter-faced over recent starts (or season/league fallback)."
    ),
    "recent_k_rate_tier": (
        "Which fallback tier produced recent_k_rate: recent_weighted | season_average | league_default."
    ),
    "recent_k_rate_starts_used": "How many prior starts fed recent_k_rate.",
    "park_k_factor": (
        "Strikeout park factor for the game's venue (1.00 = neutral); see adapters/park_factors_static.py."
    ),
    "park_factor_available": "Whether a park factor was actually resolved (vs. neutral default).",
    "weather_adjustment": (
        "Small bounded multiplier from temperature (see features/builders.py) -- "
        "illustrative, not calibrated."
    ),
    "weather_available": "Whether a weather observation was actually resolved.",
    "rest_days": "Days since the pitcher's most recent recorded start, or null if unknown.",
    "umpire_available": "Always false in this MVP -- see adapters/umpire_stub.py.",
    "role_stability_flag": (
        "True if either expected_bf or recent_k_rate fell back below the recent-starts tier -- "
        "a weak-sample signal for the decision layer."
    ),
    "opponent_adjustment": (
        "Reserved for a future opponent-lineup-strikeout-rate adjustment; always 1.0 in this MVP -- "
        "no lineup/opponent-contact-rate adapter exists yet (see CURRENT_STATE_AUDIT.md). Kept as an "
        "explicit field (not omitted) so the model formula and decision layer already have the seam."
    ),
}
