# ADR 0015 — Hosting on Replit (Reserved VM Deployment)

**Status:** Decided in practice (live production deployment exists);
recorded here to close the gap between that reality and
`docs/DECISION_LEDGER.csv`, which listed hosting as unresolved

## Decision

The engine and frontend run together in a single Replit Reserved VM
Deployment (`cassandrahits.replit.app`), started by
`scripts/replit_start.sh` per `.replit`'s `[deployment]` section.
Postgres is not hosted on Replit (it has no managed database) — an
external provider (Neon/Supabase/etc.) is required, connected via the
`DATABASE_URL` Secret.

`docs/DECISION_LEDGER.csv` listed hosting as **unresolved**, calling for
an explicit evaluation of "reliability, cost, scheduling, databases and
observability" before committing. That evaluation didn't happen as a
discrete step — it happened empirically, through a live deployment
built and debugged in real time. This ADR records what was actually
learned, so the paper trail matches reality instead of silently leaving
the ledger's "unresolved" flag standing next to a live production URL.

## What was actually learned running on Replit

- **Reliability / observability:** no managed logging, metrics, or
  alerting beyond what the Admin page's own source-health/pipeline-run
  tracker provides. Deployment failures are diagnosed by hand via
  Replit's log viewer. A real, live deployment-networking bug (the
  public URL initially routing to the engine instead of the frontend)
  took multiple iterations to fully diagnose and fix — see
  `CURRENT_STATE_AUDIT.md` and `scripts/replit_start.sh`'s comments.
- **Scheduling:** `orchestration/scheduler.py`'s in-process background
  thread is a deliberate, honestly-documented single-instance design
  (see its own docstring and `CURRENT_STATE_AUDIT.md`'s Provisional
  section) — it would double-run without a distributed lock on a
  multi-instance deployment. Reserved VM Deployment's single-instance
  model is what makes this safe; it would need real infrastructure
  (Redis lock, DB-backed leader election, or a real job scheduler) to
  scale beyond one instance.
- **Environment quirks, not Replit-specific limitations, but real
  friction:** Replit's Nix `python312` package ships no `pip` (worked
  around via `uv`); Next.js 15's port flag didn't reliably forward
  through `pnpm run dev --` on this platform (worked around via the
  `PORT` env var). Both are documented and fixed in
  `scripts/replit_start.sh`, not silently patched over.
- **Cost:** no Replit hosting cost data is recorded here — that's a
  billing question for whoever holds the account, not something visible
  from inside this repo.
- **Workflow risk (the most significant finding, not really about
  Replit itself):** editing code directly in the Replit workspace,
  rather than treating it as deploy-only (pull from GitHub, run,
  nothing else), led to real uncommitted-workspace drift during this
  build — including a period where a second, unreviewed lines adapter
  ran in production before being caught and reconciled. This is a
  process risk of *any* platform that allows interactive in-browser
  editing of a live deployment, not specifically a Replit flaw, but it's
  the sharpest lesson from this deployment and the reason the Replit
  workspace should be treated as deploy-only going forward.

## Revisit when

Real traffic/reliability requirements exceed what a single Reserved VM
instance and an in-process scheduler can support, or a cost comparison
against a conventional cloud stack (e.g. a managed Postgres + a
container host with real observability) becomes worth doing with actual
usage data in hand.
