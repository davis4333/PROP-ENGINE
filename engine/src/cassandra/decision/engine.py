"""The decision gate: turns a model's `StrikeoutDistribution` + a line +
data-quality findings into OVER/UNDER/NO_PLAY and a decision_status tier
(ADR 0002). Only ever calls the model through `StrikeoutDistribution`'s
`mean`/`cdf()` (ADR 0003) -- never assumes Poisson or any other family.

Edge is measured against a **neutral 0.5 baseline**, never described as
an "Underdog-implied probability" (ADR 0006) -- Underdog's real payout
math is unresolved, and this gate doesn't pretend otherwise.
`DECISION_EDGE_THRESHOLD` is an explicitly provisional constant (ADR 0005),
not a calibrated business decision.

Push handling (integer lines): a half-integer line (X.5, the market's
usual convention) can never push -- `probability_push` is always 0.0.
A whole-number line CAN push (P(K == line) is a real outcome), so
`probability_under` is computed as P(K < line), never `1 -
probability_over` (which would silently fold the push probability into
"under"). No sportsbook-specific push/refund payout policy is modeled
here -- this gate only ever reports probabilities and a neutral-baseline
edge, per ADR 0006's same reasoning; how a specific vendor's payout
actually treats a push (full refund, void, etc.) is a real product
question left unresolved and undecided here, not guessed at.
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
#
# Bumped to 0.2.0 here after an audit found it was never bumped for two
# real logic changes to what gets computed for real inputs: the integer-
# line push-probability fix (probability_under was `1 - probability_over`,
# silently folding P(K==line) into "under") and the missing-line fix
# (a caller-supplied synthetic 0.5 line could compute a real "edge" and
# reach QUALIFIED against a line that was never real). Any projection
# published under "k-decision-0.1.0" cannot be distinguished as pre- or
# post-fix from decision_policy_version alone -- both those bugs and
# their fixes happened under that same version string. Documented, not
# silently left as a gap: see CURRENT_STATE_AUDIT.md.
DECISION_POLICY_VERSION = "k-decision-0.2.0"

# WARN-severity findings serious enough to downgrade an otherwise-
# qualifying edge to UNCERTAIN. Deliberately excludes DATA_MISSING (the
# umpire stub's permanent, expected, never-blocking absence) -- see
# adapters/umpire_stub.py and pit/snapshot_builder.py. Also deliberately
# excludes LINEUP_UNCONFIRMED (adapters/lineups_mlb.py): MLB commonly
# hasn't posted a lineup until roughly 1-3 hours before first pitch, so
# including it here would downgrade nearly every early-day evaluation to
# UNCERTAIN regardless of real edge -- a sweeping behavior change to how
# often anything shows QUALIFIED, not a data-quality call this build
# should make unilaterally. The finding is still recorded and visible in
# every projection's reason_codes (transparency), just not gating
# decision_status yet. Whether/when it should gate is a real product
# decision for Tyler once there's a real sense of typical lineup-posting
# timing relative to the scheduler's run hours (settings.
# auto_run_hours_local) -- not guessed at here.
QUALITY_RISK_CODES = frozenset({"STARTER_UNCONFIRMED", "DATA_STALE", "DATA_CONFLICT", "LINE_SUSPENDED"})

DECISIONS = ("OVER", "UNDER", "NO_PLAY")
DECISION_STATUSES = ("QUALIFIED", "UNCERTAIN", "HELD", "REJECTED")


@dataclass(frozen=True)
class Decision:
    decision: str
    decision_status: str
    probability_over: float | None
    probability_under: float | None
    projection_mean: float
    projection_sd: float
    edge: float
    reason_codes: list[str] = field(default_factory=list)
    decision_policy_version: str = DECISION_POLICY_VERSION
    # Always 0.0 for a half-integer line (no push is possible), a real
    # value for an integer line, None only when there's no line at all
    # (see decide()'s line=None branch). Found and fixed after an audit:
    # this build's own market data can carry integer lines (a manually
    # entered UnderDog-style line isn't guaranteed to always be X.5), and
    # probability_under used to be computed as `1 - probability_over`,
    # which silently folds P(K == line) into "under" instead of reporting
    # it separately.
    probability_push: float | None = None


def decide(
    line: float | None,
    distribution: StrikeoutDistribution,
    quality_findings: list[QualityFinding],
    edge_threshold: float | None = None,
) -> Decision:
    threshold = edge_threshold if edge_threshold is not None else settings.decision_edge_threshold

    fail_findings = [f for f in quality_findings if f.status == "fail"]
    warn_findings = [f for f in quality_findings if f.status == "warn"]
    all_codes = [f.reason_code for f in quality_findings]
    sd = getattr(distribution, "sd", math.sqrt(max(distribution.mean, 0.0)))

    if line is None:
        # No real market line for this player/market -- never invent one
        # (CLAUDE.md non-negotiable #4: "No Play" is valid, never force a
        # pick). This is a structural guarantee, not just a consequence of
        # ingestion/quality_gate.py's check_line_available already adding
        # a fail-severity MARKET_CONTEXT_INCOMPLETE finding upstream (it
        # does, and callers should still pass that finding through) --
        # even if a future caller ever forgot to run that check, passing
        # line=None here still cannot produce a forced OVER/UNDER pick or
        # a probability computed against a fake threshold. Found and fixed
        # after an audit: the previous version accepted a caller-supplied
        # synthetic 0.5 line, which -- because floor(0.5) == 0 and P(K>0)
        # is close to 1.0 for almost any real start -- could compute a
        # large "edge" against a line that was never real.
        reason_codes = list(all_codes)
        if "MARKET_CONTEXT_INCOMPLETE" not in reason_codes:
            reason_codes.append("MARKET_CONTEXT_INCOMPLETE")
        return Decision(
            decision="NO_PLAY",
            decision_status="REJECTED",
            probability_over=None,
            probability_under=None,
            probability_push=None,
            projection_mean=distribution.mean,
            projection_sd=sd,
            edge=0.0,
            reason_codes=reason_codes,
        )

    # P(strikeouts > line) -- correct for both a half-integer line (X.5,
    # no push possible) and an integer line (a whole-number line, where
    # P(K == line) is a real push probability, not part of either side).
    # floor(line) is the largest whole strikeout count NOT counted as
    # "over" either way.
    threshold_k = math.floor(line)
    probability_over = 1.0 - distribution.cdf(threshold_k)
    if float(line).is_integer():
        # P(K == line): the push case. P(K < line) = P(K <= line - 1) is
        # the true "under" probability, excluding the push -- NOT
        # `1 - probability_over`, which would silently fold the push
        # probability into "under."
        line_int = int(line)
        probability_push = distribution.cdf(line_int) - distribution.cdf(line_int - 1)
        probability_under = distribution.cdf(line_int - 1)
    else:
        probability_push = 0.0
        probability_under = 1.0 - probability_over

    if fail_findings:
        return Decision(
            decision="NO_PLAY",
            decision_status="REJECTED",
            probability_over=probability_over,
            probability_under=probability_under,
            probability_push=probability_push,
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
        probability_push=probability_push,
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
