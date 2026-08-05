# ADR 0010 — Deterministic reproducibility hash on every projection

**Status:** Decided and fully implemented

## Decision

Every `projections` row carries a `reproducibility_hash` column: a
deterministic hash (SHA-256, hex) over the exact inputs that produced that
row:

```
reproducibility_hash = sha256(
    source_snapshot_id
    + feature_set_version + sorted(feature_values as canonical JSON)
    + model_version
    + decision_policy_version
    + canonical JSON of decision-gate parameters (e.g. DECISION_EDGE_THRESHOLD)
    + git_commit_sha
)
```

Two additional columns support this: `decision_policy_version` (bumped
whenever decision-gate logic/parameters change, independent of
`model_version`) and `git_commit_sha` (the engine's running commit at
projection time, captured via `git rev-parse HEAD` or an environment
variable baked in at deploy/build time).

This lets any published projection be independently re-derived and
verified later: given the same snapshot, features, model version, and
code commit, the hash must match. A mismatch is itself a data-integrity
signal worth surfacing in the admin view.

## Status

Columns (`reproducibility_hash`, `decision_policy_version`,
`git_commit_sha`) are on the `projections` table
(`db/models/projection.py`), and `ledger/service.py` computes and sets
the hash (via `decision/engine.py`'s `reproducibility_hash()`) on every
publish — verified by an independent architecture review.
