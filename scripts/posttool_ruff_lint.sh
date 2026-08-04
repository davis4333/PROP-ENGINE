#!/usr/bin/env bash
# PostToolUse hook: fast per-file ruff lint after Write/Edit/MultiEdit on a
# Python file. Non-blocking -- always exits 0; output just surfaces in the
# transcript so lint feedback is immediate during development. The real
# gate is `make lint` / CI, not this hook.
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$REPO_ROOT/engine/.venv/bin/python"

file_path=$(jq -r '.tool_input.file_path // empty')

if [[ -n "$file_path" && -f "$file_path" && "$file_path" == *.py && -x "$PYTHON" ]]; then
  "$PYTHON" -m ruff check "$file_path"
fi

exit 0
