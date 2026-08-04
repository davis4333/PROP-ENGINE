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


def test_line_floor_semantics():
    # A .5 line: P(over 5.5) = P(K >= 6) = 1 - P(K <= 5)
    dist = PoissonStrikeoutDistribution(mean=6.0)
    result = decide(5.5, dist, [])
    assert result.probability_over == 1.0 - dist.cdf(5)


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
