#!/usr/bin/env python3
"""PreToolUse hook: block Write/Edit/MultiEdit calls that would introduce a
BLOCK-severity guardrails.py violation, checked against the *proposed*
content -- not what's currently on disk.

Write's tool_input carries the full new content directly. Edit/MultiEdit
only carry old_string/new_string, so this reconstructs what the file would
look like by applying them to the current on-disk content, stages the
result under REPO_ROOT/.guardrail_precheck/<same relative path> (which
guardrails.py's _rel_posix() treats as if it were that path -- see the
PRECHECK_PREFIX comment there), runs guardrails.py against the staged
copy, and always cleans the staged copy up afterward.

Reads the PreToolUse hook payload on stdin, writes a PreToolUse
hookSpecificOutput JSON decision (allow/deny) to stdout, always exits 0
(the decision is carried in the JSON, not the exit code).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARDRAILS = REPO_ROOT / "scripts" / "guardrails.py"
ENGINE_PYTHON = REPO_ROOT / "engine" / ".venv" / "bin" / "python"
PRECHECK_DIR = REPO_ROOT / ".guardrail_precheck"

RELEVANT_DIR_PREFIXES = ("engine/src/", "engine/tests/", "scripts/")


def _allow(reason: str | None = None) -> dict:
    out: dict = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }
    if reason:
        out["hookSpecificOutput"]["permissionDecisionReason"] = reason
    return out


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _rel(path_str: str) -> str | None:
    try:
        return Path(path_str).resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return None


def _reconstruct(tool_name: str, tool_input: dict, target: Path) -> str | None:
    if tool_name == "Write":
        return tool_input.get("content", "")
    if not target.exists():
        return None
    current = target.read_text()
    if tool_name == "Edit":
        old, new = tool_input.get("old_string", ""), tool_input.get("new_string", "")
        count = -1 if tool_input.get("replace_all") else 1
        return (
            current.replace(old, new, count)
            if count != -1
            else current.replace(old, new)
        )
    if tool_name == "MultiEdit":
        result = current
        for edit in tool_input.get("edits", []):
            old, new = edit.get("old_string", ""), edit.get("new_string", "")
            result = (
                result.replace(old, new)
                if edit.get("replace_all")
                else result.replace(old, new, 1)
            )
        return result
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        print(json.dumps(_allow()))
        return 0

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path")

    if tool_name not in ("Write", "Edit", "MultiEdit") or not file_path:
        print(json.dumps(_allow()))
        return 0

    rel = _rel(file_path)
    if (
        not rel
        or not rel.endswith(".py")
        or not any(rel.startswith(p) for p in RELEVANT_DIR_PREFIXES)
    ):
        print(json.dumps(_allow()))
        return 0

    content = _reconstruct(tool_name, tool_input, REPO_ROOT / rel)
    if content is None:
        print(json.dumps(_allow()))
        return 0

    # Mirror the target's own relative path under PRECHECK_DIR so
    # _rel_posix()'s dir-prefix rules (features/, models/, grading/,
    # tests/, etc.) apply correctly -- see PRECHECK_PREFIX in guardrails.py.
    staged = PRECHECK_DIR / rel
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text(content)

    python = str(ENGINE_PYTHON) if ENGINE_PYTHON.exists() else sys.executable
    try:
        result = subprocess.run(
            [python, str(GUARDRAILS), str(staged)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    finally:
        staged.unlink(missing_ok=True)
        # prune now-empty mirrored parent dirs back up to PRECHECK_DIR
        parent = staged.parent
        while parent != PRECHECK_DIR and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

    output = (result.stdout or "").strip()
    if result.returncode != 0:
        print(
            json.dumps(
                _deny(output or f"scripts/guardrails.py blocked this change to {rel}")
            )
        )
        return 0

    print(json.dumps(_allow(output if "WARN" in output else None)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
