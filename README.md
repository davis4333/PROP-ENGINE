# Cassandra — MLB Pitcher-Strikeout Prop Engine

A decision and transparency platform for MLB pitcher-strikeout props:
point-in-time-correct data, an append-only projection ledger, and honest
grading (wins, losses, and pushes alike — nothing hidden). See
`docs/handbook.md` for the full product spec, `CURRENT_STATE_AUDIT.md`
for exactly what's real vs. stubbed, and `docs/adr/` for the decisions
made along the way.

**The full vertical slice is built and working**: ingest → point-in-time
snapshot → feature/model → decide → publish (append-only ledger) → grade
(honest, append-only), served by a FastAPI backend and a Next.js
frontend (Today / Results Ledger / Admin), backed by Postgres. See
`CURRENT_STATE_AUDIT.md` for the itemized real-vs-stubbed breakdown —
several inputs (umpire data, real Underdog line acquisition, official
paid MLB data) are deliberately stubbed behind swappable adapters, not
silently faked.

## Quickest path: Docker Compose

```bash
cp .env.example .env
docker compose up -d          # postgres + engine (FastAPI, :8000) + web (Next.js, :3000)
docker compose exec engine alembic upgrade head
```

Open **http://localhost:3000** (Today page). The engine API is at
**http://localhost:8000** (`/health`, `/api/today`, `/api/ledger`,
`/api/admin/status`).

Migrations are *not* applied automatically on container start (kept as
an explicit, visible step) — run the command above once after the first
`docker compose up`. `web` mounts source with live reload, matching
`engine`'s `--reload`.

## Seeding and running the first test slate

The engine ships with a real historical MLB slate (2023‑06‑15, Blue Jays
@ Orioles and friends) with a hand-picked set of lines chosen so their
*real, recorded* outcomes deliberately produce one of each required
result — a win, a loss, a push, plus qualified plays and no-plays. See
`engine/tests/fixtures/demo_slate/README.md` for exactly which pitchers
and why. Live MLB Stats API calls can't retroactively return
`probablePitcher` data for an already-`Final` historical game, so this
replays real saved API responses instead of hitting the network —
deterministic and fully offline.

`scripts/seed_demo_slate.py` isn't containerized (it isn't part of the
`engine` image) — run it from the host, against whichever Postgres is
running (Docker Compose's `postgres` service publishes `5432` to the
host, so this works whether `engine`/`web` are running via Docker Compose
or manually):

```bash
make install               # once, if you haven't already -- creates engine/.venv
make seed-demo
# or directly:
#   DATABASE_URL=postgresql+psycopg://cassandra:cassandra_dev_only@localhost:5432/cassandra \
#     engine/.venv/bin/python scripts/seed_demo_slate.py
```

Expected output: 20 evaluated projections, 4 QUALIFIED, 16 NO_PLAY, and
graded picks showing a WIN, a LOSS, and a PUSH. Then visit:

- `http://localhost:3000/?slate_date=2023-06-15` — Today page for that slate.
- `http://localhost:3000/ledger?slate_date=2023-06-15` — the graded results.
- `http://localhost:3000/admin` — enter the admin secret
  (`change-me-dev-only` by default, see `.env`) to see source health and
  the pipeline stage tracker for that run.

`make seed-demo` is idempotent-ish: rerunning it publishes new projection
*versions* (the ledger is append-only — see ADR 0002) rather than
duplicating games; the Today/Ledger pages always show the current
version.

## Manual local setup (no Docker for the app processes)

Requirements: Docker (for Postgres only), Python 3.12, `uv`, Node 20+,
`pnpm`. See `docs/DEVELOPMENT.md` for the full toolchain table.

```bash
cp .env.example .env
make install            # uv-installs engine/[dev], pnpm-installs web/
make db-up               # docker compose up -d postgres
make migrate-check        # alembic upgrade head

# Terminal 1 -- engine API
cd engine && .venv/bin/uvicorn cassandra.api.main:app --reload
# -> http://localhost:8000

# Terminal 2 -- frontend
cd web && pnpm run dev
# -> http://localhost:3000

# Terminal 3 -- seed the demo slate (see above), or drive the pipeline directly:
cd engine
.venv/bin/cassandra run-slate 2026-08-04        # live MLB data, today's real slate
.venv/bin/cassandra grade 2026-08-04             # once games are Final
.venv/bin/cassandra --help                        # ingest / snapshot / run-slate / grade
```

## Verifying everything works

```bash
make verify
```

Runs the full gate in order: `ruff check` + `eslint`, `ruff format
--check` + `prettier --check`, `mypy` + `tsc --noEmit`, `bandit` +
`pip-audit`, `scripts/guardrails.py`'s point-in-time/immutability
safeguards, `alembic upgrade head` against an empty-or-current database,
the full pytest suite (engine unit/integration/API/**point-in-time
leakage** tests, `scripts/tests`), `vitest` + `playwright` (including
axe accessibility checks) for the frontend, and `next build`. This is
also what CI runs on every push (`.github/workflows/ci.yml`).

To specifically confirm migrations apply cleanly from an empty database
(one of the release-readiness checks):

```bash
docker compose down -v && docker compose up -d postgres
make migrate-check
```

## Deploying to Replit

Replit has no managed Postgres, so you need a free external one first —
[Neon](https://neon.tech) or [Supabase](https://supabase.com) both work
and take under a minute to set up.

1. **Get a Postgres connection string.** Create a free Neon (or
   Supabase) project and copy its connection string as given — Cassandra
   accepts `postgres://`, `postgresql://`, or `postgresql+psycopg://`
   directly and normalizes it to the `psycopg3` driver internally
   (`config.py`'s `Settings.database_url` validator), so no manual prefix
   editing is needed.
2. **Import this repository into Replit** (Replit → Create → Import from
   GitHub). It picks up `.replit` and `replit.nix` automatically
   (Python 3.12, Node 20, pnpm, `psql`).
3. **Add Secrets** (Replit's padlock icon in the sidebar), at minimum:
   - `DATABASE_URL` — the connection string from step 1, unmodified.
   - `ADMIN_SHARED_SECRET` — any string you choose (this gates the Admin
     page; see ADR 0011 — it's explicitly not production-grade auth).
   - Optionally `DECISION_EDGE_THRESHOLD` / `OPERATING_TIMEZONE` to
     override the defaults in `.env.example`.
   - Optionally `ODDS_API_KEY` — a real key from
     [the-odds-api.com](https://the-odds-api.com) switches lines from the
     manual/fixture drop-folder to real regulated-sportsbook pitcher-
     strikeout totals (`adapters/lines_odds_api.py`). This is **not**
     Underdog's own DFS pick'em lines — Underdog has no public API; see
     `CURRENT_STATE_AUDIT.md`'s Provisional section. Never commit a real
     key anywhere in the repo — Secrets only.
4. **Click Run.** `scripts/replit_start.sh` installs both the engine and
   frontend dependencies, applies migrations, starts the engine API on
   `:8000`, and starts the frontend on `:3000` (the one port Replit
   exposes publicly — the Admin page's browser-side calls are proxied to
   the engine through that same origin by `web/next.config.ts`, so
   nothing else needs to be exposed). First run installs everything and
   will take a few minutes; subsequent runs are fast.
5. Once it's up, seed the demo slate from the Replit Shell (this is what
   populates the Ledger page — the demo slate is a real historical date,
   not today, so it won't show up on the Today page; see step 6a):
   ```bash
   DATABASE_URL="$DATABASE_URL" engine/.venv/bin/python scripts/seed_demo_slate.py
   ```
6. **Today populates itself automatically** — `replit_start.sh` runs the
   engine with `AUTO_SCHEDULER_ENABLED=true`
   (`orchestration/scheduler.py`), which fires `run_slate()` once daily
   (07:00 in `OPERATING_TIMEZONE` by default — override with
   `AUTO_RUN_HOUR_LOCAL`) and re-attempts grading recent slates on every
   poll tick, so no manual CLI/cron setup is needed for a live slate.
   6a. To see it immediately rather than waiting for the next scheduled
       run, trigger one by hand from the Replit Shell:
       ```bash
       DATABASE_URL="$DATABASE_URL" engine/.venv/bin/python -m cassandra.cli.main run-slate --date "$(date +%F)"
       ```
7. For a persistent public deployment (not just the live-editing
   workspace), use Replit's **Deployments** feature — `.replit`'s
   `[deployment]` section is already configured to run the same startup
   script, which switches to a production `next build`/`next start` when
   Replit's `REPLIT_DEPLOYMENT` variable is set (done automatically by
   Replit Deployments).
8. **After publishing, verify the public URL actually serves the
   frontend, not the engine.** A real failure mode was hit during this
   build: a Reserved VM deployment's public port defaulted to the
   engine's `:8000` instead of the frontend's `:3000`, so the public
   domain served raw JSON 404s (`{"detail":"Not Found"}`, `server:
   uvicorn` in the response headers) for `/`, `/ledger`, and `/admin`
   even though `/health` and `/api/today` worked fine (the engine does
   have those routes). `scripts/replit_start.sh` now binds the engine to
   `127.0.0.1` instead of `0.0.0.0` (it's only ever called by the
   frontend on the same machine, so it never needed to be reachable
   externally) — the best available diagnosis is that this stops it
   being a candidate at all for whatever port-auto-detection the
   deployment was doing. If a fresh redeploy after pulling that change
   still serves the engine on the public URL, go into the Deployment's
   networking/port settings in Replit's UI and explicitly select port
   `3000` as the public port instead. Either way, confirm with `curl -I`
   against the deployed root URL that you get real HTML (or at least
   `content-type: text/html`), not a JSON body, before considering the
   deployment done.

This configuration has been exercised against a live Replit account,
including a Reserved VM Deployment (external Neon/Supabase Postgres,
`AUTO_SCHEDULER_ENABLED` firing a real daily `run_slate()`, real lines
from `adapters/lines_odds_api.py`) — but it has NOT been trouble-free:
see step 8 above for a real deployment-networking bug hit in production,
and `scripts/replit_start.sh`'s comments for two Replit-Nix-specific
startup fixes (no `pip` in the Nix Python package; Next.js 15's port
flag not reliably forwarding through `pnpm run dev --`) that were lost
on a prior GitHub sync and had to be reapplied.

## Repository layout

```
engine/                     Python (FastAPI + SQLAlchemy + Alembic)
  src/cassandra/
    db/                       models, Alembic migrations, session
    adapters/                  SourceAdapter implementations (schedule, probable
                                 pitchers, game logs, weather, park factors, umpire
                                 stub, lines-manual, final box scores)
    ingestion/                  generic ingest + data-quality gate
    pit/                         point-in-time as-of primitives + snapshot builder
    features/, models/, decision/  feature engineering, baseline Poisson model,
                                     the OVER/UNDER/NO_PLAY decision gate
    ledger/, grading/             append-only projection ledger, honest grading
    orchestration/                 run_slate() / grade_slate_run() tying it together
    api/, cli/                      FastAPI app + Typer CLI (ingest/snapshot/run-slate/grade)
  tests/
    unit/, integration/, api/       full coverage of the above
    pit/                             adversarial point-in-time leakage suite -- must always pass
    fixtures/                         real saved API responses + the demo slate
web/                        Next.js (App Router, TypeScript strict)
  src/app/                    Today ("/"), Ledger ("/ledger"), Admin ("/admin")
  src/components/              shared presentational components (unit-tested)
  src/lib/                      typed API client + response types
  e2e/                           Playwright + axe accessibility tests
scripts/
  guardrails.py                Static point-in-time/immutability safeguard checks
  seed_demo_slate.py             Seeds + runs the fixture demo slate end to end
  replit_start.sh                 Replit entrypoint
docs/
  handbook.md, adr/*.md         Product spec + engineering decision records
  DEVELOPMENT.md, AI_ENGINEERING_CONTROLS.md   toolchain + Claude Code tooling reference
CLAUDE.md                    Read order, non-negotiables, do-not-do list
```

## Non-negotiables (see `CLAUDE.md` for the full list)

- Future-data leakage is a release blocker (`docs/adr/0001`) — enforced
  by `pit/asof.py` and a dedicated adversarial test suite
  (`engine/tests/pit/`).
- Published projection/grade records are immutable/append-only, enforced
  at the Postgres grant level (not just convention) — see the three
  migrations in `engine/src/cassandra/db/migrations/versions/`.
- "No Play" is a valid, expected decision — every evaluated projection is
  logged, not just qualified picks.
- Every projection carries provenance/timestamps/model+policy versions
  and a reproducibility hash (`docs/adr/0010`).
- Losses are never deleted; grading is honest (WIN/LOSS/PUSH/VOID/NO_PLAY).
