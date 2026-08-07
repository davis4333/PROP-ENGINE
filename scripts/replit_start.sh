#!/usr/bin/env bash
# Replit entrypoint: installs deps (idempotent), migrates the database,
# then starts the engine API and the frontend (the one publicly exposed
# port -- see .replit) as two supervised background processes. In
# deployment mode, if either one exits unexpectedly the whole script
# tears the other down and exits non-zero -- see the `wait -n` block
# below -- so a dead engine can never leave the frontend serving alone
# and looking falsely healthy.
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

if [ -n "${REPLIT_DEPLOYMENT:-}" ]; then
  # =========================================================
  # DEPLOYMENT MODE
  # =========================================================
  # node_modules and .next were pre-built by the deployment build
  # step (see [deployment] build in .replit). Run engine setup in
  # the background so Next.js can start immediately and open port
  # 3000 within Replit's 60-second port-open window.
  #
  # Timeline (target):
  #   t+0s  VM boots, script starts
  #   t+3s  `next start` opens port 3000  <-- healthcheck satisfied
  #   t+35s engine ready on 127.0.0.1:8000 (background)
  (
    echo "==> [engine] Installing engine dependencies"
    if [ ! -d "$REPO_ROOT/engine/.venv" ]; then
      uv venv "$REPO_ROOT/engine/.venv"
    fi
    uv pip install --quiet \
      --python "$REPO_ROOT/engine/.venv/bin/python" \
      -e "$REPO_ROOT/engine[dev,training]"

    echo "==> [engine] Applying database migrations"
    (cd "$REPO_ROOT/engine" && .venv/bin/python -m alembic upgrade head)

    # AUTO_SCHEDULER_ENABLED: fires run_slate() at 07:00 ET and re-grades
    # every 15 min. Off by default in config.py so that CLI/test runs
    # of the engine don't silently hit live MLB APIs.
    #
    # --host 127.0.0.1, not 0.0.0.0: the frontend reaches the engine
    # over localhost (see .replit API_BASE_URL and web/next.config.ts).
    # Binding loopback-only prevents Replit's port-detector from
    # picking up port 8000 as the public endpoint instead of 3000.
    echo "==> [engine] Migrations complete -- starting engine API on 127.0.0.1:8000 (auto-scheduler enabled)"
    (cd "$REPO_ROOT/engine" && \
      AUTO_SCHEDULER_ENABLED=true \
      .venv/bin/uvicorn cassandra.api.main:app \
        --host 127.0.0.1 --port 8000)
  ) &
  ENGINE_PID=$!

  echo "==> Production start (Next.js pre-built in deployment build step)"
  # PORT env var, not `-- --port 3000` -- the latter doesn't reliably
  # reach Next.js 15's CLI through pnpm's script-arg forwarding on
  # Replit; PORT is Next's own documented port override and isn't
  # dependent on that forwarding working. Backgrounded (not run in the
  # foreground as before) so this script can supervise it alongside the
  # engine -- see the `wait -n` block below for why.
  (cd "$REPO_ROOT/web" && PORT=3000 pnpm run start) &
  WEB_PID=$!

  trap 'kill "$ENGINE_PID" "$WEB_PID" 2>/dev/null || true' EXIT

  # Phase 2A: supervise both processes for the life of the deployment.
  # Previously the frontend ran in the foreground while the engine ran
  # as an unwatched background job -- a migration failure or an
  # uncaught engine startup exception left the engine subshell dead
  # while Next.js kept serving on port 3000, looking "healthy" to
  # Replit's port-based healthcheck indefinitely even though every API
  # call the frontend makes to the engine would silently fail from then
  # on. Exactly one engine process and one frontend process are
  # expected to run for the entire life of a healthy deployment, so
  # either one exiting on its own -- for any reason -- is itself the
  # failure signal; `wait -n` (no PID args, supported since bash 4.3)
  # blocks until whichever background job finishes first. Whichever
  # died, this kills the other and exits non-zero so Replit sees a
  # crashed deployment (visibly unhealthy / restart-eligible) instead
  # of a half-alive one silently serving broken pages forever.
  wait -n
  exit_code=$?
  if kill -0 "$ENGINE_PID" 2>/dev/null; then
    echo "==> [FATAL] frontend process (PID $WEB_PID) exited unexpectedly (code $exit_code) -- tearing down the deployment" >&2
  else
    echo "==> [FATAL] engine process (PID $ENGINE_PID) exited unexpectedly (code $exit_code) -- tearing down the deployment" >&2
  fi
  exit "${exit_code:-1}"

else
  # =========================================================
  # DEV / WORKSPACE MODE
  # =========================================================
  echo "==> Installing engine dependencies"
  if [ ! -d "$REPO_ROOT/engine/.venv" ]; then
    uv venv "$REPO_ROOT/engine/.venv"
  fi
  uv pip install --quiet \
    --python "$REPO_ROOT/engine/.venv/bin/python" \
    -e "$REPO_ROOT/engine[dev,training]"

  echo "==> Applying database migrations"
  (cd "$REPO_ROOT/engine" && .venv/bin/python -m alembic upgrade head)

  echo "==> Starting the engine API on 127.0.0.1:8000 (auto-scheduler enabled)"
  (cd "$REPO_ROOT/engine" && \
    AUTO_SCHEDULER_ENABLED=true \
    .venv/bin/uvicorn cassandra.api.main:app \
      --host 127.0.0.1 --port 8000) &
  ENGINE_PID=$!
  trap 'kill $ENGINE_PID 2>/dev/null || true' EXIT

  echo "==> Installing frontend dependencies"
  (cd "$REPO_ROOT/web" && pnpm install --frozen-lockfile)

  echo "==> Dev server (interactive Repl workspace)"
  (cd "$REPO_ROOT/web" && PORT=3000 pnpm run dev)
fi
