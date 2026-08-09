"""Human-readable "why Cassandra likes this play" / "risks to know about"
strings for the Today page (mission directive: qualified plays must show
why Cassandra likes them, and that must come from actual stored features
and calculations -- never an AI inventing reasons after the fact).

Pure function over already-computed, already-stored values: the features
blob written to `feature_values` by features/builders.py, the
probabilities/edge decision/engine.py already computed, and the
reason-code catalog. No new judgment happens here -- this only translates
numbers that already exist into sentences.
"""

from __future__ import annotations

from cassandra.decision.reason_codes import describe

# Reason codes whose description already appears verbatim as a "risk" --
# used to avoid a code that legitimately gates decision_status (e.g.
# EDGE_BELOW_THRESHOLD) also getting a redundant, differently-worded
# mention from the feature-derived checks below.
_TIER_LABELS = {
    "recent_weighted": "recent-starts",
    "season_average": "season-average",
    "league_default": "league-average default (little/no real sample)",
}


def _tier_label(tier: object) -> str:
    if isinstance(tier, str) and tier in _TIER_LABELS:
        return _TIER_LABELS[tier]
    return str(tier)


def build_explanation(
    *,
    decision: str,
    decision_status: str,
    projection_mean: float | None,
    line: float | None,
    edge: float | None,
    features: dict[str, object] | None,
    reason_codes: list[str],
) -> tuple[list[str], list[str]]:
    """Returns (why, risks). `why` is only ever populated for a real
    OVER/UNDER call -- a NO_PLAY has nothing to "like," only reasons it
    was rejected, which already live in `risks`. `risks` always includes
    every reason code's human description (nothing hidden), plus a
    feature-derived weak-sample note when the features blob itself
    recorded one (role_stability_flag)."""
    why: list[str] = []
    risks: list[str] = [describe(code) for code in reason_codes]

    if decision in ("OVER", "UNDER") and features is not None:
        if projection_mean is not None and line is not None:
            direction = "above" if decision == "OVER" else "below"
            distance = abs(projection_mean - line)
            why.append(
                f"Projected {projection_mean:.2f} strikeouts vs a line of {line:g} -- "
                f"{distance:.2f} {direction} the line."
            )

        recent_k_rate = features.get("recent_k_rate")
        if isinstance(recent_k_rate, int | float):
            tier = _tier_label(features.get("recent_k_rate_tier"))
            starts = features.get("recent_k_rate_starts_used")
            why.append(
                f"Recent strikeout rate {recent_k_rate * 100:.1f}% of batters faced "
                f"({tier}, {starts} starts)."
            )

        expected_bf = features.get("expected_bf")
        if isinstance(expected_bf, int | float):
            tier = _tier_label(features.get("expected_bf_tier"))
            starts = features.get("expected_bf_starts_used")
            why.append(f"Expected {expected_bf:.1f} batters faced this start ({tier}, {starts} starts).")

        park_factor = features.get("park_k_factor")
        if isinstance(park_factor, int | float) and abs(park_factor - 1.0) >= 0.01:
            direction = "favors" if park_factor > 1.0 else "works against"
            why.append(f"Park factor {park_factor:.2f}x {direction} strikeouts.")

        weather_adj = features.get("weather_adjustment")
        if isinstance(weather_adj, int | float) and abs(weather_adj - 1.0) >= 0.01:
            direction = "boosts" if weather_adj > 1.0 else "reduces"
            why.append(f"Weather adjustment {weather_adj:.2f}x {direction} the projection.")

        if edge is not None:
            why.append(f"Edge over the neutral 50% baseline: {edge * 100:.1f} points.")

    if decision_status == "QUALIFIED" and features is not None and features.get("role_stability_flag"):
        risks.append(
            "Limited recent-start sample -- expected batters faced and/or recent K-rate "
            "fell back to a season- or league-average estimate rather than true recent form."
        )

    return why, risks


__all__ = ["build_explanation"]
