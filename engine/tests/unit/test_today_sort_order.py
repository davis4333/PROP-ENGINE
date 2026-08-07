"""api/routers/today.py's best-picks-first sort order, tested directly
against constructed ProjectionOut objects -- no DB needed. The point:
QUALIFIED picks always sort before UNCERTAIN/HELD/REJECTED regardless of
raw probability numbers, and within a tier, higher model confidence
(max(P(over), P(under))) sorts first."""

from __future__ import annotations

from datetime import UTC, datetime

from cassandra.api.routers.today import _confidence, _today_sort_key
from cassandra.api.schemas import ProjectionOut

NOW = datetime.now(UTC)


def _projection(
    *,
    decision_status: str = "QUALIFIED",
    decision: str = "OVER",
    probability_over: float | None = 0.6,
    probability_under: float | None = 0.4,
    player_name: str = "Test Player",
) -> ProjectionOut:
    return ProjectionOut(
        projection_id="proj_1",
        logical_key="key",
        version=1,
        player_id="player_1",
        player_name=player_name,
        team=None,
        opponent=None,
        game_id="game_1",
        scheduled_start_utc=NOW,
        line=5.5,
        projection_mean=6.0,
        projection_sd=2.0,
        probability_over=probability_over,
        probability_under=probability_under,
        probability_push=None,
        decision=decision,
        decision_status=decision_status,
        reason_codes=[],
        model_version="k-model-0.1.0",
        feature_set_version="k-features-0.1.0",
        decision_policy_version="k-decision-0.2.0",
        reproducibility_hash=None,
        published_at=NOW,
        is_late_publication=False,
        record_label="LIVE",
    )


def test_confidence_is_the_max_of_the_two_probabilities():
    p = _projection(probability_over=0.72, probability_under=0.28)
    assert _confidence(p) == 0.72


def test_confidence_handles_missing_probabilities_as_zero():
    p = _projection(
        probability_over=None, probability_under=None, decision="NO_PLAY", decision_status="REJECTED"
    )
    assert _confidence(p) == 0.0


def test_qualified_always_sorts_before_uncertain_regardless_of_probability():
    # A REJECTED row with an extreme (but not real/tradeable) probability
    # must still sort after a QUALIFIED row with a much lower one -- the
    # tier matters more than the raw number.
    low_confidence_qualified = _projection(
        decision_status="QUALIFIED", probability_over=0.56, probability_under=0.44
    )
    high_number_rejected = _projection(
        decision_status="REJECTED",
        decision="NO_PLAY",
        probability_over=0.99,
        probability_under=0.01,
    )
    ordered = sorted([high_number_rejected, low_confidence_qualified], key=_today_sort_key)
    assert ordered == [low_confidence_qualified, high_number_rejected]


def test_within_qualified_higher_confidence_sorts_first():
    high = _projection(decision_status="QUALIFIED", probability_over=0.85, probability_under=0.15)
    low = _projection(decision_status="QUALIFIED", probability_over=0.58, probability_under=0.42)
    ordered = sorted([low, high], key=_today_sort_key)
    assert ordered == [high, low]


def test_full_tier_order_qualified_uncertain_held_rejected():
    qualified = _projection(decision_status="QUALIFIED")
    uncertain = _projection(decision_status="UNCERTAIN", decision="NO_PLAY")
    held = _projection(decision_status="HELD", decision="NO_PLAY")
    rejected = _projection(decision_status="REJECTED", decision="NO_PLAY")

    ordered = sorted([rejected, held, qualified, uncertain], key=_today_sort_key)

    assert ordered == [qualified, uncertain, held, rejected]


def test_unrecognized_decision_status_sorts_to_the_end_rather_than_crashing():
    known = _projection(decision_status="REJECTED", decision="NO_PLAY")
    unknown = _projection(decision_status="SOME_FUTURE_STATUS")
    ordered = sorted([unknown, known], key=_today_sort_key)
    assert ordered == [known, unknown]
