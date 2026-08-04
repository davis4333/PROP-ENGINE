#!/usr/bin/env bash
# PostToolUse hook: fast per-file eslint after Write/Edit/MultiEdit on a
# TypeScript/TSX file under web/src. Non-blocking -- always exits 0; output
# just surfaces in the transcript. The real gate is `make lint` / CI.
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="$REPO_ROOT/web"

file_path=$(jq -r '.tool_input.file_path // empty')

case "$file_path" in
  */web/src/*.ts | */web/src/*.tsx)
    if [[ -f "$file_path" && -d "$WEB_DIR/node_modules" ]]; then
      (cd "$WEB_DIR" && pnpm exec eslint "$file_path")
    fi
    ;;
esac

exit 0
