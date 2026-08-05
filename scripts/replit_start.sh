#!/usr/bin/env bash
# Replit entrypoint: installs deps (idempotent), migrates the database,
# starts the engine API in the background, then starts the frontend in
# the foreground on the one publicly exposed port (see .replit).
#
# Replit has no managed Postgres -- DATABASE_URL must already point at an
# external one (Neon/Supabase/Railway free tier, etc.), set as a Replit
# Secret. See README.md's "Deploying to Replit" section for exact steps.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL is not set." >&2
  echo "Replit has no managed Postgres -- add an external Postgres connection" >&2
  echo "string as a Replit Secret named DATABASE_URL. See README.md." >&2
  exit 1
fi

echo "==> Ensuring uv is available"
# Replit's Nix python312 package does not ship pip, so a plain
# `python3 -m venv` + `pip install` fails there -- uv bundles its own
# resolver/installer and doesn't need system pip at all. Installed via
# the official script (not relying on a nixpkgs `uv` derivation being
# present in this channel) and only if not already on PATH.
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

echo "==> Installing engine dependencies"
if [ ! -d "$REPO_ROOT/engine/.venv" ]; then
  uv venv "$REPO_ROOT/engine/.venv"
fi
uv pip install --quiet --python "$REPO_ROOT/engine/.venv/bin/python" -e "$REPO_ROOT/engine[dev]"

echo "==> Applying database migrations"
(cd "$REPO_ROOT/engine" && .venv/bin/python -m alembic upgrade head)

echo "==> Starting the engine API on 127.0.0.1:8000 (auto-scheduler enabled)"
# AUTO_SCHEDULER_ENABLED: a long-running Repl should populate Today and
# grade recent slates on its own -- see orchestration/scheduler.py. Off
# by default everywhere else (config.py) since a one-off CLI/test run of
# the engine shouldn't silently start hitting the live MLB API.
#
# --host 127.0.0.1, not 0.0.0.0: the frontend reaches the engine over
# localhost on this same machine/container (see .replit's API_BASE_URL
# and web/next.config.ts's rewrite) -- there's no reason for the engine
# to be reachable from outside the Repl at all. A real production bug
# was traced to this: with the engine also listening on 0.0.0.0, a
# Reserved VM Deployment's public-port auto-detection picked :8000
# (the engine) instead of :3000 (the frontend), so the public URL served
# raw API JSON/404s instead of real pages. Binding loopback-only removes
# the engine from being a public-port candidate at all.
(cd "$REPO_ROOT/engine" && AUTO_SCHEDULER_ENABLED=true .venv/bin/uvicorn cassandra.api.main:app --host 127.0.0.1 --port 8000) &
ENGINE_PID=$!
trap 'kill $ENGINE_PID 2>/dev/null || true' EXIT

echo "==> Installing frontend dependencies"
(cd "$REPO_ROOT/web" && pnpm install --frozen-lockfile)

if [ -n "${REPLIT_DEPLOYMENT:-}" ]; then
  echo "==> Production build + start (Replit Deployment)"
  # PORT env var, not `-- --port 3000` -- the latter doesn't reliably
  # reach Next.js 15's CLI through pnpm's script-arg forwarding on
  # Replit; PORT is Next's own documented port override and isn't
  # dependent on that forwarding working.
  (cd "$REPO_ROOT/web" && pnpm run build && PORT=3000 pnpm run start)
else
  echo "==> Dev server (interactive Repl workspace)"
  (cd "$REPO_ROOT/web" && PORT=3000 pnpm run dev)
fi
