"""The reason-code catalog (handbook Appendix A). Every code blocks or
qualifies publication and must carry a human-readable detail string --
never surface a bare code to the Today/Admin UI without one.

Used by both the quality gate (data-level issues, produced before/while
building a snapshot) and the decision engine (model/edge-level issues,
produced when deciding OVER/UNDER/NO_PLAY).
"""

from __future__ import annotations

REASON_CODES: dict[str, str] = {
    "DATA_STALE": "The freshest available data for this fact is older than the staleness threshold.",
    "DATA_MISSING": "A required fact was not available as of the snapshot cutoff.",
    "DATA_CONFLICT": "Two sources (or two close observations) disagree and neither was preferred.",
    "ENTITY_UNMATCHED": "A record could not be resolved to a known player/game/venue.",
    "LINE_MOVED": "The line moved meaningfully between observation and publication.",
    "LINE_SUSPENDED": "The line is marked suspended by its source as of the snapshot cutoff.",
    "LINEUP_UNCONFIRMED": "The batting lineup was not confirmed as of the snapshot cutoff.",
    "STARTER_UNCONFIRMED": "The probable starter was not confirmed as of the snapshot cutoff.",
    "ROLE_UNSTABLE": "The pitcher's role/workload pattern is too irregular to project confidently.",
    "PITCH_LIMIT_RISK": "A known pitch-count/workload restriction limits the pitcher's opportunity.",
    "WEATHER_RISK": "Weather conditions materially affect expected outcomes or game viability.",
    "MODEL_UNHEALTHY": "The model failed to produce a usable projection for this record.",
    "MODEL_DISAGREEMENT": "Multiple model signals disagree beyond an acceptable tolerance.",
    "UNCERTAINTY_HIGH": "Projection uncertainty is too high relative to the edge to act on.",
    "EDGE_BELOW_THRESHOLD": "The model's edge over the neutral decision baseline is below the gate.",
    "MARKET_CONTEXT_INCOMPLETE": "Line/market context needed to evaluate this prop is incomplete.",
    "LATE_BREAKING_CHANGE": "A material input changed after the snapshot was frozen.",
    "MANUAL_HOLD": "An operator manually held this projection from qualifying/publishing.",
}


def describe(code: str) -> str:
    return REASON_CODES.get(code, f"Unrecognized reason code: {code}")
