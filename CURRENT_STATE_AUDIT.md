# Current State Audit

Updated as part of the toolchain-establishment pass. Repo started
completely empty (0 commits) at the start of this build.

## What's real (implemented, tested, passing)

- **Repo scaffold**: `docker-compose.yml`, `.env.example`, `README.md`,
  `Makefile` (`make verify` and its constituent targets), CI
  (`.github/workflows/ci.yml` — engine + web jobs, both green), CodeQL
  workflow, Dependabot config.
- **Docs**: the owner's handoff package copied into `docs/` (handbook,
  decision ledger, backlog, diagrams), 13 ADRs recording every
  plan-approval amendment, `CLAUDE.md`, `docs/DEVELOPMENT.md`,
  `docs/AI_ENGINEERING_CONTROLS.md`.
- **Engine toolchain**: Python 3.12 + uv, full quality/testing dependency
  set (pytest + asyncio/cov/xdist, hypothesis, testcontainers,
  time-machine, respx, ruff, mypy, bandit, pip-audit), all clean against
  the current codebase.
- **Frontend toolchain**: Next.js (App Router, TS strict) + pnpm in
  `web/`, ESLint, Prettier, Vitest + React Testing Library, Playwright +
  axe-core accessibility assertions, all passing. Only a placeholder page
  exists — no real Today/Ledger/Admin UI yet (ADR 0012: intentional,
  waits for the engine vertical slice + PIT suite).
- **`scripts/guardrails.py`**: static safeguards (immutable-table
  mutation, box-score leakage, migration tampering, disabled tests,
  hardcoded secrets, publication-cutoff awareness, as-of cutoff
  awareness), 16 passing regression tests in `scripts/tests/`, wired into
  both CI and a Claude Code PreToolUse hook.
- **DB schema (SQLAlchemy models only — no migration generated yet)**:
  `engine/src/cassandra/db/models/` — identity, source registry, all 9
  `raw_*` immutable ingestion tables, snapshots, features, the amended
  `projections` ledger (reproducibility hash, decision policy version,
  publication-cutoff fields), append-only `grades`, `audit_events`,
  pipeline run tracking. All 24 tables import cleanly and register with
  SQLAlchemy metadata; ruff/mypy clean.
- **Claude Code tooling**: 6 skills, 7 subagents (including the
  independent/adversarial `point-in-time-auditor`), PreToolUse/PostToolUse
  hooks — all individually pipe-tested and verified against both benign
  and deliberately-bad inputs. See `docs/AI_ENGINEERING_CONTROLS.md` for
  the activation caveat on the hooks (needs `/hooks` or a fresh session).

## What's stubbed / not yet built

- **No Alembic migration exists yet** — the models above are defined but
  `alembic upgrade head` currently has nothing to apply (verified: it
  runs cleanly with zero revisions). Generating the initial migration
  (plus the `REVOKE UPDATE, DELETE` immutability grants) is the next
  piece of engine work.
- **No adapters, ingestion service, point-in-time snapshot builder,
  feature pipeline, model, decision engine, ledger writer, grading
  engine, orchestration, FastAPI routes, or CLI exist yet.** These are
  Phase 1 (K Data) through Phase 3 (Ledger) of the vertical-slice plan —
  none of that engine logic has been written. `engine/tests/pit/` (the
  leakage regression suite) doesn't exist yet either.
- **`web/` has no real pages** — placeholder only, per ADR 0012.

## Known placeholders / provisional decisions (do not treat as final)

- `DECISION_EDGE_THRESHOLD=0.05` in `.env.example` — an arbitrary
  placeholder, not a calibrated or business-approved value (ADR 0005).
- The 0.5 neutral decision baseline is explicitly *not* an
  "Underdog-implied probability" (ADR 0006) — real payout math is
  unresolved.
- Umpire data source is permanently a stub (`is_available=False`) — no
  reliable free source exists.
- Underdog lines come from a manual/fixture importer, not a real
  integration — scraping is explicitly avoided pending a ToS-compliant
  acquisition method (unresolved per the handbook).
- Admin API auth (`ADMIN_SHARED_SECRET`) is a demo-only shared secret,
  not production auth (ADR 0011).
- `decision`/`decision_status` vocabulary (ADR 0002) is this build's
  interpretation of the handbook's Appendix B — only one example row
  exists in the spec, so this pairing hasn't been cross-checked against a
  second real example yet.

## Not automatable from this session (need a human with repo admin)

Branch protection on `main`, Dependabot *security alerts* (separate from
the version-update PRs, which do activate automatically), and native
GitHub secret scanning all need to be toggled in GitHub's Settings UI (or
via `gh`/the REST API) by someone with admin access — no tool available in
this session exposes those endpoints. Full detail in
`docs/AI_ENGINEERING_CONTROLS.md`.

## Next smallest task

Generate the initial Alembic migration from the existing models (including
the immutability `REVOKE` grants), then build the `SourceAdapter` base
contract and the simplest concrete adapter (static park factors) end to
end, per the approved build plan's Phase 0/1 sequencing.
