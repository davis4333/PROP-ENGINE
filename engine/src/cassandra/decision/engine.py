"""The decision gate: turns a model's `StrikeoutDistribution` + a line +
data-quality findings into OVER/UNDER/NO_PLAY and a decision_status tier
(ADR 0002). Only ever calls the model through `StrikeoutDistribution`'s
`mean`/`cdf()` (ADR 0003) -- never assumes Poisson or any other family.

Edge is measured against a **neutral 0.5 baseline**, never described as
an "Underdog-implied probability" (ADR 0006) -- Underdog's real payout
math is unresolved, and this gate doesn't pretend otherwise.
`DECISION_EDGE_THRESHOLD` is an explicitly provisional constant (ADR 0005),
not a calibrated business decision.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field

from cassandra.config import settings
from cassandra.ingestion.quality_gate import QualityFinding
from cassandra.models.interface import StrikeoutDistribution

# Bumped whenever this decision logic/thresholds change, independent of
# model_version (ADR 0010) -- a projection permanently pins whichever
# policy version produced it.
DECISION_POLICY_VERSION = "k-decision-0.1.0"

# WARN-severity findings serious enough to downgrade an otherwise-
# qualifying edge to UNCERTAIN. Deliberately excludes DATA_MISSING (the
# umpire stub's permanent, expected, never-blocking absence) -- see
# adapters/umpire_stub.py and pit/snapshot_builder.py.
QUALITY_RISK_CODES = frozenset({"STARTER_UNCONFIRMED", "DATA_STALE", "DATA_CONFLICT", "LINE_SUSPENDED"})

DECISIONS = ("OVER", "UNDER", "NO_PLAY")
DECISION_STATUSES = ("QUALIFIED", "UNCERTAIN", "HELD", "REJECTED")


@dataclass(frozen=True)
class Decision:
    decision: str
    decision_status: str
    probability_over: float
    probability_under: float
    projection_mean: float
    projection_sd: float
    edge: float
    reason_codes: list[str] = field(default_factory=list)
    decision_policy_version: str = DECISION_POLICY_VERSION


def decide(
    line: float,
    distribution: StrikeoutDistribution,
    quality_findings: list[QualityFinding],
    edge_threshold: float | None = None,
) -> Decision:
    threshold = edge_threshold if edge_threshold is not None else settings.decision_edge_threshold

    fail_findings = [f for f in quality_findings if f.status == "fail"]
    warn_findings = [f for f in quality_findings if f.status == "warn"]
    all_codes = [f.reason_code for f in quality_findings]

    # P(strikeouts > line). Lines are conventionally X.5, so floor(line)
    # is the largest whole strikeout count still counted as "under."
    threshold_k = math.floor(line)
    probability_over = 1.0 - distribution.cdf(threshold_k)
    probability_under = 1.0 - probability_over
    sd = getattr(distribution, "sd", math.sqrt(max(distribution.mean, 0.0)))

    if fail_findings:
        return Decision(
            decision="NO_PLAY",
            decision_status="REJECTED",
            probability_over=probability_over,
            probability_under=probability_under,
            projection_mean=distribution.mean,
            projection_sd=sd,
            edge=0.0,
            reason_codes=all_codes,
        )

    edge_over = probability_over - 0.5
    edge_under = probability_under - 0.5
    side, edge = ("OVER", edge_over) if edge_over >= edge_under else ("UNDER", edge_under)

    reason_codes = list(all_codes)
    risk_present = any(f.reason_code in QUALITY_RISK_CODES for f in warn_findings)

    if edge < threshold:
        if "EDGE_BELOW_THRESHOLD" not in reason_codes:
            reason_codes.append("EDGE_BELOW_THRESHOLD")
        decision_status = "UNCERTAIN"
        decision = "NO_PLAY"
    elif risk_present:
        decision_status = "UNCERTAIN"
        decision = "NO_PLAY"
    else:
        decision_status = "QUALIFIED"
        decision = side

    return Decision(
        decision=decision,
        decision_status=decision_status,
        probability_over=probability_over,
        probability_under=probability_under,
        projection_mean=distribution.mean,
        projection_sd=sd,
        edge=edge,
        reason_codes=reason_codes,
    )


def reproducibility_hash(
    *,
    source_snapshot_id: str,
    feature_set_version: str,
    features: dict[str, object],
    model_version: str,
    decision_policy_version: str,
    edge_threshold: float,
    git_commit_sha: str | None,
) -> str:
    """A deterministic hash (ADR 0010) over exactly the inputs that
    produced a projection, so it can be independently re-derived later.
    Same snapshot + features + model/policy versions + parameters + code
    commit must always hash identically."""
    canonical = json.dumps(
        {
            "source_snapshot_id": source_snapshot_id,
            "feature_set_version": feature_set_version,
            "features": features,
            "model_version": model_version,
            "decision_policy_version": decision_policy_version,
            "edge_threshold": edge_threshold,
            "git_commit_sha": git_commit_sha,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
