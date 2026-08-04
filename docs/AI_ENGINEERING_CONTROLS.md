# AI Engineering Controls

This documents the Claude-Code-specific tooling layered on top of the
engine/web codebase: skills, subagents, hooks, CI checks, and MCP/tool
scope. It exists so a human reviewer (or a future Claude Code session)
can see exactly what's automated, what's advisory, and what still needs a
manual step in GitHub's settings that no tool in this environment can
perform.

## Skills (`.claude/skills/`)

Project-scoped skills that trigger automatically when their `description`
matches the request, or explicitly via `/skill-name`:

| Skill | Triggers on |
|---|---|
| `cassandra-pit-audit` | Reviewing/writing anything touching `raw_*` tables, snapshots, features, or the decision engine — walks the ADR 0001 cutoff checklist. |
| `cassandra-projection-review` | Changes to `decision/`, `models/`, `features/`, `ledger/service.py` — decision vocabulary, reason codes, ADR 0006 wording, reproducibility hash. |
| `cassandra-ledger-integrity` | Changes touching `raw_*`/`projections`/`grades`/`audit_events` or admin action endpoints — immutability invariants, pipeline state guards. |
| `cassandra-data-adapter` | Adding or editing a `SourceAdapter`. |
| `cassandra-ui` | Working in `web/` — ADR 0012 scope limit, design language, transparency tiers. |
| `cassandra-release-gate` | End of any task — `make verify`, Definition of Done, `CURRENT_STATE_AUDIT.md` upkeep. |

## Subagents (`.claude/agents/`)

| Subagent | Tools | Role |
|---|---|---|
| `architecture-reviewer` | Read, Grep, Glob, Bash | Scope creep, over-abstraction, drift from the adapter/pipeline contracts. |
| `point-in-time-auditor` | Read, Grep, Glob, Bash — **no Edit/Write** | Independent, adversarial leakage audit. See below. |
| `model-validator` | Read, Grep, Glob, Bash | Statistical soundness of the strikeout model, version-bumping discipline. |
| `test-engineer` | Read, Edit, Write, Grep, Glob, Bash | Writes/reviews `engine/tests/pit/` and fixtures. |
| `security-reviewer` | Read, Grep, Glob, Bash | Secrets, bandit/pip-audit findings, admin-auth-placeholder misuse, SQL injection surface. |
| `frontend-reviewer` | Read, Grep, Glob, Bash | ADR 0012 scope, TS strict, accessibility, design language. |
| `documentation-auditor` | Read, Grep, Glob, Bash | `CURRENT_STATE_AUDIT.md`/ADRs/`CLAUDE.md` vs. actual code and test evidence. |

**`point-in-time-auditor` independence, by construction:** its tool
allowlist excludes `Edit`/`Write`, so it structurally cannot "fix" the
code it's auditing — it can only find and report. Its system prompt
explicitly instructs it to assume the implementer missed something, never
to reuse the reasoning of whoever wrote the change, and to construct a
concrete leaking record/cutoff scenario rather than eyeballing the diff.
This is a convention enforced by the agent's own prompt and tool
restriction, not by a platform-level guarantee that a different *session*
invokes it — the practice this repo expects is: run the PIT audit as a
separate subagent call, never fold "and also check for leakage" into the
same turn that wrote the feature.

## Hooks (`.claude/settings.json`)

### PreToolUse — blocking guardrails check

Matcher `Write|Edit|MultiEdit` → `scripts/pretool_guardrails_check.py`.

Write's tool input carries the full proposed file content directly; Edit
and MultiEdit only carry `old_string`/`new_string`, so this hook
reconstructs what the file *would* look like by applying the edit to the
current on-disk content, stages the result under
`.guardrail_precheck/<same relative path>` (gitignored, always cleaned up
after — see the `PRECHECK_PREFIX` handling in `scripts/guardrails.py`),
and runs the full `scripts/guardrails.py` check suite against that staged
copy. If it finds a **BLOCK**-severity violation, the hook denies the
tool call via `hookSpecificOutput.permissionDecision: "deny"` with the
violation as the reason; **WARN**-severity findings are surfaced back as
`permissionDecisionReason` on an `allow` decision, never blocking.

The hook is deliberately **fail-open**: if `pretool_guardrails_check.py`
itself crashes or times out, the settings.json command falls back to
`allow` rather than hanging or blocking all edits. This is a conscious
tradeoff — the same checks are enforced unconditionally in CI
(`make guardrails` in the `engine` job), so a hook failure degrades to
"caught at CI/PR time instead of at edit time," not "never caught."

**Verified before being considered done** (see the conversation this file
was authored in, or re-run yourself):
- The raw command was pipe-tested with synthesized stdin for a benign
  Edit (allow), a Write introducing a real BLOCK violation (deny, correct
  reason text, correct relative path), and an irrelevant file (allow,
  no-op).
- `jq -e` confirmed the JSON is valid and the hook is correctly nested
  under `hooks.PreToolUse[].hooks[]` with `type: "command"`.
- A **live** Edit tool call in the authoring session was *not* blocked
  despite being a deliberately bad edit — because `.claude/settings.json`
  did not exist when that session started, so its file-watcher wasn't
  covering `.claude/`. This is a known Claude Code behavior, not a bug in
  the hook: run `/hooks` once (reloads config) or start a fresh session to
  activate it. Confirm activation the same way — attempt a deliberately
  bad `Edit` and confirm it's denied — before relying on this hook.

### PostToolUse — non-blocking lint feedback

Matcher `Write|Edit|MultiEdit`, two hooks, both always exit 0:
- `scripts/posttool_ruff_lint.sh` — runs `ruff check` on the touched file
  if it's a `.py` file that exists on disk. Pipe-tested against both a
  clean file (passes silently) and a file with real issues (reports them,
  still exits 0).
- `scripts/posttool_eslint_lint.sh` — runs `pnpm exec eslint` on the
  touched file if it's a `.ts`/`.tsx` file under `web/src/`. Pipe-tested
  the same way, including confirming it actually detects a real
  `@typescript-eslint/no-unused-vars` violation and still exits 0.

These are fast, local, "notice it now" checks. The authoritative gate is
still `make lint` / CI.

## CI (`.github/workflows/`)

- **`ci.yml`** — two jobs on every push/PR:
  - `engine`: ruff (lint), ruff format --check, mypy, bandit, pip-audit
    (`--skip-editable`, since the local `cassandra-engine` package isn't
    published to PyPI and would otherwise false-positive), `scripts/
    guardrails.py` against the whole tracked tree, `alembic upgrade head`
    against a real Postgres service container, then `pytest` (includes
    `engine/tests/pit/`) with coverage.
  - `web`: typecheck, eslint, prettier --check, vitest, Playwright (with
    axe accessibility assertions), and `next build`.
- **`codeql.yml`** — standalone workflow (push to `main`, PRs into `main`,
  weekly schedule) running CodeQL for both `python` and
  `javascript-typescript`.
- **`dependabot.yml`** — weekly version-update PRs for `pip` (`/engine`),
  `npm` (`/web`), `docker` (`/engine`), and `github-actions` (`/`), with
  dev-dependency grouping to reduce PR noise.

## What could **not** be automated from this session

The GitHub MCP tools available in this environment cover issues, PRs,
files, commits, Actions, and secret-scanning-on-a-snippet — there is no
tool here that can call GitHub's repo-settings or branch-protection REST
endpoints. The following need a human with repo admin access (or `gh`/the
GitHub UI) to actually turn on, even though the supporting files are
already committed:

1. **Branch protection on `main`** — require the `engine` and `web` CI
   jobs (and, once it exists, an explicit PIT-suite check) as required
   status checks before merge; require PRs; consider requiring review.
2. **Dependabot security alerts** — distinct from the version-update PRs
   `dependabot.yml` already drives (those activate automatically once
   merged to the default branch); vulnerability alerts are a separate
   Settings → Security toggle.
3. **Secret scanning** (GitHub's native repo-wide scanner, distinct from
   the `run_secret_scanning` MCP tool this session used only for
   spot-checking specific files) — Settings → Security → Secret scanning.
4. **CodeQL default setup vs. this workflow** — once `codeql.yml` is on
   `main` and has run successfully, results appear in the Security tab
   automatically; no extra toggle needed for that part specifically, but
   confirm "Code scanning" shows results after the first run.

Until (1) is done, nothing stops a direct push to `main` or a merge with
failing CI.

## MCP / tool scope

- **GitHub MCP** (`mcp__github__*`) — available and used for repo file/PR
  context in this session. No PR was opened as part of this task.
- **Playwright** — used as an npm test dependency (`web/`'s
  `test:e2e`), not as an MCP server; no browser-automation MCP server was
  added.
- **PostgreSQL** — local development only. `DATABASE_URL` in
  `.env.example`/`docker-compose.yml` points at a local container; no
  production or shared database is configured anywhere in this repo.
- **No other MCP servers were installed.** Per explicit instruction, this
  session did not add Stripe, social-media-automation, Kubernetes,
  paid-data-vendor, or production-infrastructure integrations of any
  kind — those remain out of scope until a human decides otherwise (the
  handbook itself marks the real Underdog/MLB-vendor integration as an
  unresolved decision; see `docs/adr/0013` and `CURRENT_STATE_AUDIT.md`).
