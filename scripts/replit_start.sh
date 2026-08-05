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

echo "==> Installing engine dependencies"
python3 -m venv "$REPO_ROOT/engine/.venv" --clear=false 2>/dev/null || true
"$REPO_ROOT/engine/.venv/bin/pip" install --quiet --upgrade pip
"$REPO_ROOT/engine/.venv/bin/pip" install --quiet -e "$REPO_ROOT/engine[dev]"

echo "==> Applying database migrations"
(cd "$REPO_ROOT/engine" && .venv/bin/python -m alembic upgrade head)

echo "==> Starting the engine API on :8000 (auto-scheduler enabled)"
# AUTO_SCHEDULER_ENABLED: a long-running Repl should populate Today and
# grade recent slates on its own -- see orchestration/scheduler.py. Off
# by default everywhere else (config.py) since a one-off CLI/test run of
# the engine shouldn't silently start hitting the live MLB API.
(cd "$REPO_ROOT/engine" && AUTO_SCHEDULER_ENABLED=true .venv/bin/uvicorn cassandra.api.main:app --host 0.0.0.0 --port 8000) &
ENGINE_PID=$!
trap 'kill $ENGINE_PID 2>/dev/null || true' EXIT

echo "==> Installing frontend dependencies"
(cd "$REPO_ROOT/web" && pnpm install --frozen-lockfile)

if [ -n "${REPLIT_DEPLOYMENT:-}" ]; then
  echo "==> Production build + start (Replit Deployment)"
  (cd "$REPO_ROOT/web" && pnpm run build && pnpm run start -- --port 3000)
else
  echo "==> Dev server (interactive Repl workspace)"
  (cd "$REPO_ROOT/web" && pnpm run dev -- --port 3000)
fi
