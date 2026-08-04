---
name: cassandra-release-gate
description: The pre-completion checklist to run before declaring any Cassandra task done, opening a PR, or reporting work as finished — make verify (lint, typecheck, security, tests, migration check, guardrails, frontend checks), the Definition of Done from CLAUDE.md/handbook Appendix C, and whether CURRENT_STATE_AUDIT.md needs updating. Use at the end of any task, not mid-task.
---

# Cassandra release gate

Run this before saying a task is done. It is a gate, not a formality — a
task that skips this and turns out to have a failing PIT test or an
un-updated audit doc is not actually finished per this repo's own rules.

## 1. Run `make verify`

```
make verify
```

This is the single entry point expected to run, in order: lint (`ruff
check engine/src engine/tests`), typecheck (`mypy` per
`engine/pyproject.toml`'s `[tool.mypy]` config), security (`bandit -c
engine/pyproject.toml` and `pip-audit`), the full engine test suite
(`pytest engine/tests`, which includes `engine/tests/pit/` — the
`pit` marker in `pyproject.toml` documents these as "must always pass"),
an Alembic migration check (`alembic upgrade head` applies cleanly, and
ideally `alembic check`/autogenerate-diff is empty), `scripts/
guardrails.py` (the point-in-time structural checks — see
`cassandra-pit-audit`), and, once `web/` has real pages, frontend checks
(`tsc --noEmit`, lint, `axe` accessibility pass per `cassandra-ui`/
`frontend-reviewer`). If any individual command isn't wired into `make
verify` yet for the current state of the repo, run it directly instead of
skipping it silently.

If `make verify` (or its constituent commands) is not yet present for
part of the repo (e.g. frontend checks before `web/` has real pages),
say so explicitly in your completion report rather than silently treating
that check as passed.

## 2. Definition of Done (CLAUDE.md / handbook Appendix C)

Walk this list literally, item by item, and be ready to point to evidence
for each — not just assert it:

- Requirement linked to a confirmed decision (`docs/DECISION_LEDGER.csv`)
  or an ADR in `docs/adr/`. If it isn't, that's a gap to flag, not fill in
  by inventing a decision (`CLAUDE.md` non-negotiable #7).
- Tests added and passing — cite the actual test file(s) and command run,
  not "tests pass" without specifics.
- Point-in-time behavior verified — if the change touches anything
  upstream of the decision engine, `pytest engine/tests/pit` must have
  been run and passed (`CLAUDE.md`'s Definition of Done is explicit about
  this).
- Error/stale-data behavior is visible — a reason code (Appendix A) or
  admin warning, never a silent degradation. If a code path can encounter
  missing/stale/conflicting data, confirm there's a visible signal for it,
  not just a `None`/empty-list fallback.
- `CURRENT_STATE_AUDIT.md` updated if what's real vs. stubbed changed (see
  step 3 below).
- No secrets committed, no unsafe/ToS-violating data collection added —
  specifically re-check for any Underdog scraping (`CLAUDE.md`'s do-not-do
  list forbids this outright) and no credentials/API keys in the diff.

The handbook's own Appendix C additionally expects: implementation
reviewed at the correct architectural boundary, admin view updated (if the
change affects something the Admin page should surface), documentation and
diagram updated, and the change summarized in plain language with a visual
demonstration where practical — hold non-trivial engine changes to this
bar too, not just frontend changes.

## 3. Update `CURRENT_STATE_AUDIT.md` if reality changed

If the task made something real that was previously stubbed/missing (or
vice versa — e.g. a new adapter replacing a stub, the leakage suite going
from absent to passing, a new ADR-governed placeholder introduced), update
`CURRENT_STATE_AUDIT.md` to reflect it. This file exists specifically so a
future session (human or Claude Code) can trust what's actually
implemented versus aspirational — letting it drift out of sync is exactly
the failure mode `documentation-auditor` exists to catch, so don't rely on
that agent to catch it after the fact when you already know what changed.

## 4. Use the task protocol's report format

Per `CLAUDE.md`'s task protocol, close out with: **What you understood ·
Files inspected · Plan · Changes made · Tests and evidence · Data-integrity
impact · Remaining risks · Next smallest task.** "Data-integrity impact"
specifically means stating, even if the answer is "none": did this change
touch anything upstream of the decision engine, and if so, what leakage
risk was checked and how.
