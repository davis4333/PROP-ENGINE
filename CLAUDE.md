# Cassandra — Claude Code Operating Instructions

## Read order (do this before touching code)

1. `docs/CLAUDE_START_HERE.md` — original owner handoff instructions.
2. `docs/DECISION_LEDGER.csv` — confirmed vs. unresolved product decisions.
3. `docs/handbook.md` — full spec (`## Confirmed Decisions`, `## Product
   Constitution`, and each major section's opening paragraph carry the
   real content; the "Required implementation contract" /
   "Acceptance evidence" blocks repeat verbatim per subsection and can be
   skimmed).
4. `docs/adr/` — decisions made *during this build* that refine or
   constrain the handbook (read all of them; they're short).
5. `CURRENT_STATE_AUDIT.md` — what's actually real vs. stubbed right now.

## Non-negotiables (from the handbook, do not violate)

1. MLB only, pitcher strikeouts only, for now.
2. Future-data leakage is a release blocker — see ADR 0001.
3. Published projection records are immutable/append-only. Never `UPDATE`
   or `DELETE` a `raw_*`, `projections`, `grades`, or `audit_events` row —
   the DB grants enforce this (see the initial migration), so if a query
   needs an UPDATE there, the design is wrong, not the grant.
4. "No Play" is a valid, expected decision — never force a pick.
5. Every projection carries provenance/timestamps/versions, including the
   reproducibility hash (ADR 0010).
6. Grades: win/loss/push/void/no-play. Losses are never deleted.
7. Do not invent missing product decisions marked "unresolved" in the
   handbook or `DECISION_LEDGER.csv`. Build around them with a clean seam
   (see the adapter contract) and document the placeholder, don't guess
   silently.

## Do-not-do list

- Do not add an `is_current`/mutable-flag column to `projections` or
  `grades` — "current" is always derived by query (see ADR 0002/schema
  comments). Adding one would make the immutability guarantee false.
- Do not read `raw_final_box_scores` from anywhere except `grading/`.
- Do not hardcode a specific distribution family into `decision/engine.py`
  — it must only call the `StrikeoutModel` interface (ADR 0003).
- Do not call the neutral 0.5 decision baseline an "Underdog-implied
  probability" anywhere (ADR 0006) — Underdog's real payout math is
  unresolved.
- Do not add pages beyond Today/Ledger/Admin to `web/` without checking
  with the owner first (ADR 0012).
- Do not scrape Underdog. Lines come from the manual/fixture adapter
  until a real, ToS-compliant acquisition method is confirmed.

## Tooling

- Setup and everyday commands: `docs/DEVELOPMENT.md`. The short version:
  `make install`, `make db-up`, `make verify` (the full gate — lint,
  format, typecheck, security, guardrails, tests including the PIT suite,
  migrations, frontend checks, build).
- Skills (`.claude/skills/`) and subagents (`.claude/agents/`) exist for
  the recurring review tasks this repo needs — point-in-time leakage
  audits, ledger-integrity checks, projection/decision review, adapter
  authoring, UI scope, and the release-gate checklist. Prefer them over
  re-deriving the same checklist from scratch; full inventory and what
  each does in `docs/AI_ENGINEERING_CONTROLS.md`.
- Hooks in `.claude/settings.json` run `scripts/guardrails.py` before
  every Write/Edit/MultiEdit on engine/scripts Python files (blocks
  immutable-table mutation, box-score leakage, migration tampering,
  disabled tests, hardcoded secrets) and ruff/eslint after, non-blocking.
  If a hook doesn't seem to be firing, run `/hooks` once to reload —
  see `docs/AI_ENGINEERING_CONTROLS.md` for why that's sometimes needed.
- `point-in-time-auditor` is deliberately independent and adversarial —
  run it as its own subagent call on anything upstream of the decision
  engine, never fold its checklist into the same turn that wrote the
  change.

## Task protocol / required response format

For every task, report: What you understood · Files inspected · Plan ·
Changes made · Tests and evidence · Data-integrity impact · Remaining
risks · Next smallest task. (From `docs/CLAUDE_START_HERE.md`.)

## Branching

Work on the currently checked-out branch unless told otherwise; commit
with descriptive messages; do not force-push.

## Definition of done (Appendix C of the handbook)

- Requirement linked to a confirmed decision or an ADR in `docs/adr/`.
- Tests added and passing.
- Point-in-time behavior verified (run the `engine/tests/pit/` suite if
  touching anything upstream of the decision engine).
- Error/stale-data behavior is visible (a reason code or admin warning),
  never a silent degradation.
- `CURRENT_STATE_AUDIT.md` updated if what's real/stubbed changed.
- No secrets committed; no unsafe/ToS-violating data collection added.
