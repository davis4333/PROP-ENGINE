# Current State Audit

Updated at the end of the full vertical-slice MVP build. The repo started
completely empty (0 commits); every item below except the "Not real" and
"Provisional" sections is implemented, tested, and verified working
against real (not mocked) data during this build.

## What's real (implemented, tested, verified)

### Database

- Full Postgres schema (`engine/src/cassandra/db/models/`): identity
  (venues/teams/players/games), source registry + health, 9 `raw_*`
  immutable ingestion tables, snapshots (+ raw refs + data-quality
  findings), feature sets/values, the projection ledger, append-only
  grades, audit events, pipeline run/stage tracking.
- Three Alembic migrations, applying cleanly from an empty database
  (verified repeatedly this session, including a from-scratch rebuild
  immediately before this audit was written):
  1. `f4b13ecb5ad7` — initial schema + `REVOKE UPDATE, DELETE` on every
     immutable table.
  2. `d764bb3bb5c1` — corrects a gap found empirically during this build:
     the REVOKE-only design breaks for any table a foreign key
     *references* (Postgres requires `UPDATE` privilege for the
     `FOR KEY SHARE` row lock FK inserts need, even though the inserting
     role never intends to mutate the parent row). Grants `UPDATE` back
     and replaces real mutation-blocking with a `BEFORE UPDATE OR DELETE`
     trigger that unconditionally raises — still DB-enforced, not
     convention.
  3. `ee1a1af7126d` — closes a second gap found the same way: Postgres
     grants `TRUNCATE` to a table's owner by default, and `f4b13ecb5ad7`
     never revoked it. `TRUNCATE` doesn't fire row triggers, so REVOKE is
     the only available defense; confirmed it doesn't reopen the FK-lock
     problem.
- Immutability is enforced by Postgres itself for `raw_*`, `projections`,
  `grades`, `audit_events` — not just application convention.

### Ingestion

- 8 source adapters, all tested against real saved API responses (not
  synthetic fixtures): MLB schedule, probable pitchers, pitcher game
  logs, Open-Meteo weather, static park factors, a permanent umpire
  stub (`is_available=False` — see Provisional below), a manual/fixture
  lines importer, and MLB final box scores.
- Generic ingestion service + data-quality gate (stale/missing/conflict/
  market-incomplete checks), with source health tracking and an
  append-only audit trail.

### Point-in-time correctness

- `pit/asof.py`'s three primitives (`latest_as_of`, `all_as_of`,
  `latest_grouped_as_of`) are the sole gate for historical reads —
  `ingested_at` (real wall-clock write time) AND `observed_at` (source's
  claimed effective time) must both be `<= cutoff`.
- `pit/snapshot_builder.py` freezes a point-in-time view of a slate
  purely through those primitives; reruns at the same cutoff never
  mutate a prior snapshot.
- A dedicated adversarial leakage suite (`engine/tests/pit/`, 19 tests)
  tries to make the wrong (leaked) answer look attractive — a late
  "correction" that's the true latest, observed_at backdating in both
  directions, a starter swap arriving after cutoff, a sentinel value
  seeded directly into `raw_final_box_scores` for the exact player/game
  being projected — and asserts it's refused every time. `raw_final_box_scores`
  is structurally unreachable from `pit/`, `features/`, or `models/`
  (AST-verified, not just documented) — only `grading/` reads it, and
  only `game_status='Final'` rows.

### Features, model, decision

- Feature engineering (`features/`): expected batters faced and
  decay-weighted recent K-rate with documented fallback tiers
  (recent-weighted → season-average → league-default), park/weather
  adjustments, a `role_stability_flag` signal when a fallback tier was
  used.
- Baseline model (`k-model-0.1.0`, `models/baseline.py`): a deliberately
  simple, interpretable formula (not a trained model — the pre-comparison
  naive baseline the backlog calls for), strikeouts modeled as Poisson.
  The decision engine only ever calls the model through the
  `StrikeoutModel`/`StrikeoutDistribution` interface (ADR 0003) — no
  distribution family is hardcoded outside `models/`.
- Decision engine (`decision/engine.py`, `k-decision-0.1.0`): edge vs. a
  neutral 0.5 baseline (never called an "Underdog-implied probability" —
  ADR 0006), the full Appendix A reason-code catalog, OVER/UNDER/NO_PLAY
  × QUALIFIED/UNCERTAIN/HELD/REJECTED.

### Ledger and grading

- Append-only projection ledger (`ledger/service.py`): every publish is
  an INSERT; "current" is always `DISTINCT ON (logical_key) ORDER BY
  version DESC`, never a mutable flag (ADR 0002); reproducibility hash
  over snapshot + features + model/policy versions + git commit (ADR
  0010); late-publication flagging (ADR 0008).
- Honest, append-only grading (`grading/service.py`): WIN/LOSS/PUSH/VOID/
  NO_PLAY, only grades published projections against `Final` box scores
  (ADR 0007), idempotent (a correction — a later Final box score for the
  same outing — appends a new grade rather than duplicating or mutating).

### Orchestration, API, CLI

- `orchestration/run_slate.py`: `run_slate()` (INGEST → VALIDATE → FREEZE
  → PROJECT → REVIEW → PUBLISH, one call) and `grade_slate_run()`, both
  writing full `pipeline_runs`/`pipeline_run_stages` detail. Publishes a
  row for every confirmed starter, including ones with no market line
  (REJECTED/`MARKET_CONTEXT_INCOMPLETE`, `line=None`) — transparency
  holds even without a prop to grade.
- FastAPI app (`api/`): `GET /health`, `GET /api/today`, `GET /api/ledger`
  (+`/{projection_id}` history), `GET /api/admin/status`, `POST
  /api/admin/runs/{slate_date}/{run,grade}` — the admin routes gated by
  ADR 0011's shared-secret header.
- Typer CLI (`cassandra` console script): `ingest`, `snapshot`,
  `run-slate`, `grade`.
- Live-verified against the real MLB Stats API (not fixtures) for a
  real slate during this build: 30 real pitchers ingested (453 real
  game-log rows), correctly frozen/projected/published.

### Fixture demo slate

- A real historical slate (2023-06-15) with a hand-picked
  `lines_manual` drop file covering 4 of its 20 real probable starters,
  chosen so their *real recorded* outcomes deliberately produce a WIN, a
  LOSS, a PUSH, plus 16 other real starters correctly falling out as
  NO_PLAY (no line). `scripts/seed_demo_slate.py` (`make seed-demo`)
  replays it via saved real API fixtures (live network can't
  retroactively return `probablePitcher` for an already-`Final` game —
  confirmed empirically) and runs the real pipeline against a real
  Postgres database.

### Frontend

- Next.js App Router, TypeScript strict: Today (`/`), Results Ledger
  (`/ledger`), Admin (`/admin`) — the three pages ADR 0012 scopes this
  build to. Admin is gated by the same shared-secret header, entered
  client-side and proxied to the engine through Next.js's own origin
  (`next.config.ts` rewrite) rather than needing a second exposed port —
  works the same locally, in Docker Compose, and on a single-port host.
- Verified live end to end against the real seeded demo slate: screenshots
  captured of all three pages showing real projections, real WIN/LOSS/
  PUSH grades, real source health, and all 7 pipeline stages with real
  statuses.

### Tests, tooling, CI

- 166 engine + scripts tests (unit, integration, API, the point-in-time
  leakage suite) — all passing on a freshly rebuilt database.
- Frontend: 15 Vitest component tests, 7 Playwright + axe accessibility
  tests, `next build` succeeds.
- `make verify` (lint, format-check, typecheck, `bandit` + `pip-audit`,
  `scripts/guardrails.py`, migrations-from-empty, the full test suite,
  frontend gate, build) passes clean end to end.
- `scripts/guardrails.py`: 21 regression tests, wired into CI and a
  Claude Code PreToolUse hook.
- CI (`.github/workflows/ci.yml`): engine job + web job, matching `make
  verify`'s checks.

## Provisional / deliberately stubbed (documented, not silent)

These are the handbook's own "unresolved" items, built behind clean
swappable seams rather than guessed at, per `CLAUDE.md`'s instruction not
to invent missing product decisions:

- **Umpire data**: permanent stub, always `is_available=False` — no
  reliable free source exists. Never blocks a decision (a deliberate
  WARN, excluded from `QUALITY_RISK_CODES`).
- **Underdog lines**: a manual/fixture drop-folder importer, not a real
  Underdog integration — Underdog's real acquisition method/ToS is
  legally unresolved per the handbook; scraping was explicitly avoided.
- **Official paid MLB data**: free MLB Stats API used instead — no paid
  vendor integration exists.
- **Park factors**: a small static/seeded table
  (`adapters/park_factors_static.py`); only venue_id=2 (Camden Yards) is
  confirmed against a real vendor, the rest are common approximations.
  Unknown venues fall back to neutral with a visible warning.
- **Weather coordinates**: `orchestration/run_slate.py`'s
  `VENUE_COORDINATES` static lookup only has Camden Yards — other venues
  simply get no weather record (a visible gap, not a guess).
- **`DECISION_EDGE_THRESHOLD=0.05`**: an explicitly provisional constant
  (ADR 0005), not calibrated or business-approved.
- **Neutral 0.5 decision baseline**: never described as an
  "Underdog-implied probability" (ADR 0006) — real payout math is
  unresolved.
- **Opponent adjustment**: always neutral (1.0) in the baseline model —
  no opponent-lineup-contact-rate adapter exists yet; the feature field
  is kept explicit (not omitted) as a documented seam.
- **Admin auth**: a demo-only shared-secret header (ADR 0011), not
  production authentication.
- **Admin actions**: only `run` and `grade` are implemented. ADR 0007
  describes a richer revalidate/regenerate/publish state-guard split;
  that ADR's own status note marks it "Not yet implemented," deferred
  past this MVP.
- **Frontend scope**: Today/Ledger/Admin only (ADR 0012) — no All
  Projections, Player View, or Methodology pages.

## Verified against real infrastructure

- **Replit deployment**: `.replit`, `replit.nix`, and
  `scripts/replit_start.sh` were exercised against a live Replit account
  (external managed Postgres, both services running under
  `replit_start.sh`). Confirmed working: migrations applied cleanly,
  `make seed-demo`'s target script populated a real historical slate,
  Today/Ledger/Admin all rendered real data (Ledger showing the seeded
  2×WIN/1×LOSS/1×PUSH), and the Admin shared-secret gate worked. One real
  friction point found and fixed: managed Postgres providers (Neon,
  Supabase, Replit's own Postgres, Heroku-style hosts) hand out
  `postgresql://`/`postgres://` connection strings, but SQLAlchemy needs
  `postgresql+psycopg://` or it falls back to a driver this project
  doesn't install — `config.py`'s `Settings.database_url` now rewrites
  either scheme automatically, so a pasted-in connection string works
  without manual editing.

## Not verified against real infrastructure this session

- **Docker Compose**: `docker-compose.yml` (postgres + engine + web) is
  validated via `docker compose config` (schema/interpolation check) and
  every constituent piece — Postgres, `uvicorn`, `next dev`/`next build`
  — was run and verified directly outside Docker (this sandboxed session
  has no Docker daemon available). The compose file itself has not been
  exercised with an actual `docker compose up`.

## Not automatable from this session (need a human with repo admin)

Branch protection on `main`, Dependabot security alerts (separate from
the version-update PRs, which do activate automatically), and native
GitHub secret scanning all need to be toggled in GitHub's Settings UI by
someone with admin access. Full detail in
`docs/AI_ENGINEERING_CONTROLS.md`.

## Next smallest task (if continuing past this MVP)

Real Underdog line acquisition (pending a confirmed ToS-compliant
method), a paid/official MLB data vendor, umpire data, and Phase-4-scope
work (ADR 0007's fuller admin action state machine, calibrating
`DECISION_EDGE_THRESHOLD` against real backtested performance) are the
handbook's explicitly unresolved product decisions this build built
around rather than guessed at — each is a clean adapter/seam swap, not a
rearchitecture.
