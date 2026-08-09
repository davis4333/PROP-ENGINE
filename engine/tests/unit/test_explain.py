"""decision/explain.py -- "why Cassandra likes this play" must come from
actual stored features/probabilities, never an invented-after-the-fact
reason. These tests exercise every branch a real Today-page card can hit:
a real QUALIFIED call, a NO_PLAY with no line, a NO_PLAY from a risk
downgrade, and the weak-sample risk note."""

from __future__ import annotations

from cassandra.decision.explain import build_explanation


def _features(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "expected_bf": 24.3,
        "expected_bf_tier": "recent_weighted",
        "expected_bf_starts_used": 6,
        "recent_k_rate": 0.284,
        "recent_k_rate_tier": "recent_weighted",
        "recent_k_rate_starts_used": 6,
        "park_k_factor": 1.00,
        "weather_adjustment": 1.00,
        "role_stability_flag": False,
    }
    base.update(overrides)
    return base


def test_qualified_over_produces_grounded_why_bullets_from_stored_features():
    why, risks = build_explanation(
        decision="OVER",
        decision_status="QUALIFIED",
        projection_mean=6.8,
        line=5.5,
        edge=0.12,
        features=_features(),
        reason_codes=[],
    )

    assert any("6.80" in b and "5.5" in b for b in why)
    assert any("28.4%" in b for b in why)
    assert any("24.3" in b for b in why)
    assert any("12.0 points" in b for b in why)
    assert risks == []


def test_no_play_with_no_line_has_no_why_and_explains_the_rejection():
    why, risks = build_explanation(
        decision="NO_PLAY",
        decision_status="REJECTED",
        projection_mean=6.8,
        line=None,
        edge=0.0,
        features=None,
        reason_codes=["MARKET_CONTEXT_INCOMPLETE"],
    )

    assert why == []
    assert len(risks) == 1
    assert "market" in risks[0].lower() or "line" in risks[0].lower()


def test_no_play_from_edge_below_threshold_explains_why_it_was_rejected():
    why, risks = build_explanation(
        decision="NO_PLAY",
        decision_status="UNCERTAIN",
        projection_mean=6.1,
        line=5.5,
        edge=0.02,
        features=_features(),
        reason_codes=["EDGE_BELOW_THRESHOLD"],
    )

    # NO_PLAY never gets "why I like it" bullets -- there's nothing to like.
    assert why == []
    assert any("edge" in r.lower() for r in risks)


def test_park_and_weather_bullets_only_appear_when_meaningfully_non_neutral():
    why, _ = build_explanation(
        decision="UNDER",
        decision_status="QUALIFIED",
        projection_mean=4.2,
        line=5.5,
        edge=0.15,
        features=_features(park_k_factor=1.08, weather_adjustment=0.97),
        reason_codes=[],
    )
    assert any("Park factor 1.08x favors" in b for b in why)
    assert any("Weather adjustment 0.97x reduces" in b for b in why)

    why_neutral, _ = build_explanation(
        decision="UNDER",
        decision_status="QUALIFIED",
        projection_mean=4.2,
        line=5.5,
        edge=0.15,
        features=_features(park_k_factor=1.00, weather_adjustment=1.00),
        reason_codes=[],
    )
    assert not any("Park factor" in b for b in why_neutral)
    assert not any("Weather adjustment" in b for b in why_neutral)


def test_qualified_with_weak_sample_surfaces_a_risk_note_the_ui_must_show():
    _, risks = build_explanation(
        decision="OVER",
        decision_status="QUALIFIED",
        projection_mean=6.8,
        line=5.5,
        edge=0.12,
        features=_features(recent_k_rate_tier="league_default", role_stability_flag=True),
        reason_codes=[],
    )
    assert any("weak" not in r.lower() and "limited recent-start sample" in r.lower() for r in risks)


def test_reason_codes_always_translate_to_human_descriptions_never_bare_codes():
    _, risks = build_explanation(
        decision="NO_PLAY",
        decision_status="REJECTED",
        projection_mean=None,
        line=None,
        edge=None,
        features=None,
        reason_codes=["DATA_STALE", "DATA_CONFLICT"],
    )
    assert "DATA_STALE" not in risks
    assert "DATA_CONFLICT" not in risks
    assert len(risks) == 2
