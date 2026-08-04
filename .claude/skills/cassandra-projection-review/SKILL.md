---
name: cassandra-projection-review
description: Review changes to the decision/model/feature layer (decision/engine.py, models/, features/, ledger/service.py) for correct decision/decision_status vocabulary (ADR 0002), Appendix A reason codes, the ADR 0006 neutral-baseline wording rule, ADR 0010 reproducibility hash population, and ADR 0003 model-interface distribution-agnosticism. Use when reviewing or writing anything that produces or shapes a projections row.
---

# Cassandra projection/decision layer review

This is the checklist for anything that writes to `projections`
(`engine/src/cassandra/db/models/projection.py`) or feeds that write —
`models/`, `features/`, `decision/engine.py`, `ledger/service.py`.

## 1. `decision` vs. `decision_status` vocabulary (ADR 0002)

These are two orthogonal fields — never conflate them or use one where the
other belongs:

- `decision` ∈ `{OVER, UNDER, NO_PLAY}` — the directional call.
- `decision_status` ∈ `{QUALIFIED, UNCERTAIN, HELD, REJECTED}` — the
  confidence/gating tier.

Check the CHECK constraints in `projection.py` (`DECISIONS`,
`DECISION_STATUSES`) are respected — no code path should be able to write
a value outside these enums, and no code/comment/API field should describe
`decision_status` as if it were the pick itself (e.g. "the decision was
QUALIFIED" is wrong; "the call was OVER, qualified" is right).

Also verify the evaluated/qualified/published three-tier distinction is
never blurred in code, API responses, or comments:

1. **Evaluated** — every row written for the slate, regardless of decision
   or status (the transparency record).
2. **Qualified** — `decision_status = 'QUALIFIED'` rows within the
   evaluated set. Still internal/computed, not necessarily public yet.
3. **Published** — `published_at IS NOT NULL` and past the ADR 0008
   publication cutoff. The actual public record; Ledger aggregates are
   computed from published rows only.

A function or endpoint that silently filters to "qualified" when it claims
to return "all projections," or that treats "qualified" as synonymous with
"published," is a review-blocking bug per ADR 0002.

## 2. Reason codes match the Appendix A catalog

`reason_codes` (a `text[]` on `projections`) must only ever contain codes
from the handbook's Appendix A catalog: `DATA_STALE`, `DATA_MISSING`,
`DATA_CONFLICT`, `ENTITY_UNMATCHED`, `LINE_MOVED`, `LINE_SUSPENDED`,
`LINEUP_UNCONFIRMED`, `STARTER_UNCONFIRMED`, `ROLE_UNSTABLE`,
`PITCH_LIMIT_RISK`, `WEATHER_RISK`, `MODEL_UNHEALTHY`,
`MODEL_DISAGREEMENT`, `UNCERTAINTY_HIGH`, `EDGE_BELOW_THRESHOLD`,
`MARKET_CONTEXT_INCOMPLETE`, `LATE_BREAKING_CHANGE`, `MANUAL_HOLD` (plus
`EDGE_CLEARS_THRESHOLD` for the qualifying case, per handbook Appendix B's
example row). Check `decision/reason_codes.py` (Phase 3) for the canonical
list rather than trusting a hardcoded string in the calling code — a new
ad hoc code string invented at a call site instead of added to the catalog
is a review-blocking finding.

Every reason code included on a row must come with a human-readable
detail somewhere the admin/API surface can show it — a bare code with no
explanation defeats the "error/stale-data behavior is visible" Definition
of Done requirement in `CLAUDE.md`.

## 3. The 0.5 baseline is never "implied probability" (ADR 0006)

`docs/adr/0006-neutral-baseline-not-implied-probability.md`: the decision
gate compares `probability_over` against a neutral **0.5**, not an
Underdog-implied probability (Underdog's real payout/juice math is
unresolved). Grep the diff for `implied`, `implied_probability`,
`underdog_implied`, etc. anywhere near `DECISION_EDGE_THRESHOLD` or the 0.5
comparison — in code comments, docstrings, API field descriptions, and any
UI copy. The required phrasing is "neutral baseline" or "provisional
decision baseline." This is a wording rule with a real consequence (ADR
0006 explains a future reader could wrongly treat the gate as
payout-aware) — treat a violation as blocking, not stylistic.

Also confirm `DECISION_EDGE_THRESHOLD` is still treated as an explicitly
provisional placeholder (commented as such at every use site, and listed
in `CURRENT_STATE_AUDIT.md` as an open item per ADR 0005) — not quietly
promoted to a "real," calibrated constant.

## 4. Reproducibility hash fields populated (ADR 0010)

Every `projections` row must carry: `reproducibility_hash`,
`decision_policy_version`, `git_commit_sha`, plus the inputs the hash is
derived from — `source_snapshot_id`, `feature_set_version`,
`model_version`. Per ADR 0010 the hash is
`sha256(source_snapshot_id + feature_set_version + sorted(feature_values as canonical JSON) + model_version + decision_policy_version + canonical JSON of decision-gate parameters + git_commit_sha)`.
Check that:

- The hash is computed from a canonical (sorted-keys) JSON serialization,
  not Python's default dict ordering — otherwise the same inputs can
  produce different hashes on different runs, defeating the point.
- `decision_policy_version` is bumped whenever decision-gate logic or
  parameters change (independent of `model_version` — conflating the two
  is a review-blocking finding since ADR 0010 exists specifically to keep
  them independently reproducible).
- `git_commit_sha` is captured at projection time (`git rev-parse HEAD` or
  a build-time env var), not left null in a real (non-fixture) run.

## 5. Model interface stays distribution-agnostic (ADR 0003)

`decision/engine.py` must only ever call `.cdf()` / `.mean` on a
`StrikeoutDistribution`/`StrikeoutModel` (per the `models/interface.py`
contract in ADR 0003) — never assume Poisson, never reach into a
model-specific attribute, never import a specific distribution class
outside `models/baseline.py`. Grep for `poisson`, `scipy.stats`, or
`numpy.random` anywhere in `decision/` or `ledger/` — those belong only in
`models/baseline.py` (`k-model-0.1.0`). A decision-engine change that only
works because it assumes a Poisson mean/variance relationship is a
review-blocking violation of the extensibility constraint, even if
`k-model-0.1.0` is the only model that exists today.

If the change touches `features/expected_bf.py` (ADR 0004), confirm the
fallback tier actually used is recorded on the feature record (not just
the final number), and that hitting the weakest tier (league-average role
default) sets a role-stability reason code rather than silently producing
a normal-looking projection.
