from __future__ import annotations

from cassandra.decision.engine import decide, reproducibility_hash
from cassandra.ingestion.quality_gate import QualityFinding
from cassandra.models.baseline import PoissonStrikeoutDistribution


def test_clear_over_edge_is_qualified():
    # mean=8 vs line=5.5 -> P(K>5) is well above 0.5+threshold
    dist = PoissonStrikeoutDistribution(mean=8.0)
    result = decide(5.5, dist, [], edge_threshold=0.05)
    assert result.decision == "OVER"
    assert result.decision_status == "QUALIFIED"
    assert result.edge >= 0.05
    assert "EDGE_BELOW_THRESHOLD" not in result.reason_codes


def test_clear_under_edge_is_qualified():
    dist = PoissonStrikeoutDistribution(mean=2.0)
    result = decide(5.5, dist, [], edge_threshold=0.05)
    assert result.decision == "UNDER"
    assert result.decision_status == "QUALIFIED"


def test_edge_below_threshold_is_no_play_uncertain():
    # mean close to the line -> edge near zero
    dist = PoissonStrikeoutDistribution(mean=5.5)
    result = decide(5.5, dist, [], edge_threshold=0.05)
    assert result.decision == "NO_PLAY"
    assert result.decision_status == "UNCERTAIN"
    assert "EDGE_BELOW_THRESHOLD" in result.reason_codes


def test_fail_finding_forces_rejected_no_play_even_with_strong_edge():
    dist = PoissonStrikeoutDistribution(mean=9.0)
    findings = [QualityFinding("DATA_MISSING", "no probable pitcher", "fail")]
    result = decide(5.5, dist, findings, edge_threshold=0.05)
    assert result.decision == "NO_PLAY"
    assert result.decision_status == "REJECTED"
    assert result.edge == 0.0
    assert "DATA_MISSING" in result.reason_codes


def test_no_line_forces_rejected_no_play_even_with_extreme_mean():
    # Regression: decide() used to be called with a caller-substituted
    # synthetic 0.5 line when no real market line existed. Because
    # floor(0.5) == 0 and P(K>0) is close to 1.0 for almost any real
    # start, that could compute a large "edge" against a line that was
    # never real, landing as a fully QUALIFIED OVER pick. line=None must
    # now force NO_PLAY/REJECTED structurally, regardless of how extreme
    # the model's own mean is.
    dist = PoissonStrikeoutDistribution(mean=9.0)
    result = decide(None, dist, [], edge_threshold=0.05)
    assert result.decision == "NO_PLAY"
    assert result.decision_status == "REJECTED"
    assert result.edge == 0.0
    assert "MARKET_CONTEXT_INCOMPLETE" in result.reason_codes


def test_no_line_never_computes_probabilities_against_a_fake_threshold():
    dist = PoissonStrikeoutDistribution(mean=9.0)
    result = decide(None, dist, [], edge_threshold=0.05)
    assert result.probability_over is None
    assert result.probability_under is None


def test_no_line_does_not_duplicate_market_context_incomplete_already_present():
    # ingestion/quality_gate.py's check_line_available already adds this
    # same reason code as a fail-severity finding when lines_latest_first
    # is empty -- decide() must not add a second copy when the caller
    # already passed it through.
    dist = PoissonStrikeoutDistribution(mean=9.0)
    findings = [QualityFinding("MARKET_CONTEXT_INCOMPLETE", "no line", "fail")]
    result = decide(None, dist, findings, edge_threshold=0.05)
    assert result.reason_codes.count("MARKET_CONTEXT_INCOMPLETE") == 1


def test_no_line_still_reports_projection_mean_and_sd():
    # A missing line doesn't mean the model couldn't run -- only that
    # there's nothing to compare it against. The raw projection is still
    # visible (transparency), just never a betting decision.
    dist = PoissonStrikeoutDistribution(mean=9.0)
    result = decide(None, dist, [], edge_threshold=0.05)
    assert result.projection_mean == 9.0
    assert result.projection_sd == dist.sd


def test_warn_quality_risk_downgrades_otherwise_qualified_edge():
    dist = PoissonStrikeoutDistribution(mean=9.0)
    findings = [QualityFinding("STARTER_UNCONFIRMED", "not confirmed", "warn")]
    result = decide(5.5, dist, findings, edge_threshold=0.05)
    assert result.decision == "NO_PLAY"
    assert result.decision_status == "UNCERTAIN"
    assert "STARTER_UNCONFIRMED" in result.reason_codes


def test_umpire_data_missing_warn_never_downgrades():
    # DATA_MISSING as a WARN (the permanent umpire stub) must NOT push an
    # otherwise-clean qualified pick to UNCERTAIN -- it's explicitly
    # "never block" per adapters/umpire_stub.py.
    dist = PoissonStrikeoutDistribution(mean=9.0)
    findings = [
        QualityFinding("DATA_MISSING", "No reliable free umpire-assignment source is available", "warn")
    ]
    result = decide(5.5, dist, findings, edge_threshold=0.05)
    assert result.decision == "OVER"
    assert result.decision_status == "QUALIFIED"


def test_probabilities_sum_to_one():
    dist = PoissonStrikeoutDistribution(mean=6.0)
    result = decide(5.5, dist, [])
    assert result.probability_over + result.probability_under == 1.0


def test_half_integer_line_has_zero_push_probability():
    dist = PoissonStrikeoutDistribution(mean=6.0)
    result = decide(5.5, dist, [])
    assert result.probability_push == 0.0


def test_line_floor_semantics():
    # A .5 line: P(over 5.5) = P(K >= 6) = 1 - P(K <= 5)
    dist = PoissonStrikeoutDistribution(mean=6.0)
    result = decide(5.5, dist, [])
    assert result.probability_over == 1.0 - dist.cdf(5)


# --- integer-line push handling -------------------------------------------


def test_integer_line_probabilities_sum_to_one_including_push():
    dist = PoissonStrikeoutDistribution(mean=6.0)
    result = decide(5.0, dist, [])
    total = result.probability_over + result.probability_under + result.probability_push
    assert abs(total - 1.0) < 1e-12


def test_integer_line_push_is_p_of_exact_equality():
    # Regression: probability_under used to be `1 - probability_over`,
    # which silently folded P(K == line) into "under" for an integer
    # line. P(K == 5) must be its own reported value, not absorbed.
    dist = PoissonStrikeoutDistribution(mean=6.0)
    result = decide(5.0, dist, [])
    expected_push = dist.cdf(5) - dist.cdf(4)
    assert result.probability_push == expected_push
    assert expected_push > 0  # sanity: this line's push probability is real, not a degenerate zero


def test_integer_line_under_excludes_the_push_case():
    # P(under 5) = P(K < 5) = P(K <= 4) -- NOT P(K <= 5), which would
    # include the push.
    dist = PoissonStrikeoutDistribution(mean=6.0)
    result = decide(5.0, dist, [])
    assert result.probability_under == dist.cdf(4)


def test_integer_line_over_is_unaffected_by_push_handling():
    # P(over 5) = P(K > 5) = P(K >= 6) -- same formula regardless of
    # whether the line is an integer or half-integer.
    dist = PoissonStrikeoutDistribution(mean=6.0)
    result = decide(5.0, dist, [])
    assert result.probability_over == 1.0 - dist.cdf(5)


def test_integer_line_zero_is_handled_without_a_negative_cdf_call():
    # An edge case: line=0 means "under" would need P(K < 0), which is
    # structurally impossible -- must not raise or misbehave.
    dist = PoissonStrikeoutDistribution(mean=3.0)
    result = decide(0.0, dist, [], edge_threshold=0.05)
    assert result.probability_under == 0.0
    assert result.probability_push == dist.cdf(0)
    assert result.probability_over == 1.0 - dist.cdf(0)


def test_integer_line_fail_finding_still_reports_real_probabilities():
    dist = PoissonStrikeoutDistribution(mean=6.0)
    findings = [QualityFinding("DATA_MISSING", "no probable pitcher", "fail")]
    result = decide(5.0, dist, findings, edge_threshold=0.05)
    assert result.decision == "NO_PLAY"
    assert result.decision_status == "REJECTED"
    assert result.probability_push == dist.cdf(5) - dist.cdf(4)


def test_projection_sd_uses_poisson_sd_property():
    dist = PoissonStrikeoutDistribution(mean=9.0)
    result = decide(5.5, dist, [])
    assert result.projection_sd == dist.sd


def test_decision_policy_version_recorded():
    dist = PoissonStrikeoutDistribution(mean=8.0)
    result = decide(5.5, dist, [])
    assert result.decision_policy_version == "k-decision-0.1.0"


# --- reproducibility_hash ------------------------------------------------


def test_reproducibility_hash_deterministic():
    kwargs = {
        "source_snapshot_id": "snap-1",
        "feature_set_version": "k-features-0.1.0",
        "features": {"expected_bf": 23.0, "recent_k_rate": 0.25},
        "model_version": "k-model-0.1.0",
        "decision_policy_version": "k-decision-0.1.0",
        "edge_threshold": 0.05,
        "git_commit_sha": "abc123",
    }
    assert reproducibility_hash(**kwargs) == reproducibility_hash(**kwargs)


def test_reproducibility_hash_changes_with_inputs():
    base = {
        "source_snapshot_id": "snap-1",
        "feature_set_version": "k-features-0.1.0",
        "features": {"expected_bf": 23.0, "recent_k_rate": 0.25},
        "model_version": "k-model-0.1.0",
        "decision_policy_version": "k-decision-0.1.0",
        "edge_threshold": 0.05,
        "git_commit_sha": "abc123",
    }
    changed = {**base, "edge_threshold": 0.10}
    assert reproducibility_hash(**base) != reproducibility_hash(**changed)
