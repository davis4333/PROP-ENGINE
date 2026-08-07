#!/usr/bin/env python3
"""Cassandra engineering guardrails.

Static, best-effort checks that enforce the invariants in
`docs/adr/0001-point-in-time-cutoff-semantics.md`, `CLAUDE.md`'s
do-not-do list, and the handbook's immutability/transparency principles.
Used two ways:

  1. As a Claude Code PreToolUse hook (see .claude/settings.json) -- runs
     against files about to be written/edited, blocking BLOCK-severity
     violations before they land.
  2. As a `make guardrails` / CI step -- runs against the current worktree
     or a given file list.

These are deliberately conservative regex/text heuristics, not a full
static analyzer. They catch the obvious, dangerous cases; they are not a
substitute for the PIT test suite (`engine/tests/pit/`) or human review.
False positives are possible and can be reviewed/overridden by a human --
false negatives are the bigger risk this script is trying to reduce.

Usage:
    python scripts/guardrails.py [FILE ...]      # check specific files
    python scripts/guardrails.py                 # check the whole repo (tracked files)
    python scripts/guardrails.py --staged        # check git-staged files only
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

IMMUTABLE_TABLES = [
    "raw_schedule_events",
    "raw_probable_pitchers",
    "raw_lineups",
    "raw_pitcher_game_logs",
    "raw_weather_observations",
    "raw_park_factors",
    "raw_umpire_assignments",
    "raw_lines",
    "raw_final_box_scores",
    "projections",
    "grades",
    "audit_events",
    "model_artifacts",
    "model_registry_events",
]

RAW_MODEL_NAMES = [
    "RawScheduleEvent",
    "RawProbablePitcher",
    "RawLineup",
    "RawPitcherGameLog",
    "RawWeatherObservation",
    "RawParkFactor",
    "RawUmpireAssignment",
    "RawLine",
    "RawFinalBoxScore",
]

# Non-"Raw*"-prefixed ORM classes that also map to immutable tables (ledger/
# audit rows, model artifacts/registry events), needed by the mutation
# check in addition to RAW_MODEL_NAMES.
IMMUTABLE_MODEL_CLASS_NAMES = ["Projection", "Grade", "AuditEvent", "ModelArtifact", "ModelRegistryEvent"]
IMMUTABLE_BLOCK_TOKENS = (
    IMMUTABLE_TABLES + RAW_MODEL_NAMES + IMMUTABLE_MODEL_CLASS_NAMES
)

BOX_SCORE_TOKENS = ["raw_final_box_scores", "RawFinalBoxScore"]

# This file's own regression tests necessarily contain literal example
# secrets/skip-markers as fixture *string content* (to prove the checks
# below actually catch them -- see scripts/tests/test_guardrails.py). The
# authoritative check on guardrails.py's own behavior is that pytest
# suite, not a text scan of its source; exempt it here rather than
# contorting the fixture strings to dodge the very patterns they exist to
# test.
SELF_TEST_EXEMPT_PATHS = ("scripts/tests/test_guardrails.py",)

# Directories where reading raw_final_box_scores / mutating query patterns
# are legitimately expected and therefore excluded from the relevant checks.
BOX_SCORE_ALLOWED_DIRS = ("grading",)
MUTATION_EXCLUDED_DIRS = ("db/migrations",)
# "adapters" is allowed because adapters only ever *produce* RawRecords
# (referencing raw_model as a write target) -- they never query raw
# tables for a point-in-time read, so requiring ingested_at/observed_at
# cutoff tokens there was a false positive on every adapter file.
# "features" is allowed for the same reason in the opposite direction:
# feature builders only ever *consume* already as-of-resolved rows passed
# in by pit/snapshot_builder.py (Raw* names appear only as type hints) --
# they never query raw tables themselves.
ASOF_ALLOWED_DIRS = (
    "pit",
    "grading",
    "ingestion",
    "adapters",
    "features",
    "orchestration",
    "api",
    "db/migrations",
    "db/models",
    # historical/ is a structurally separate subsystem (CLAUDE.md
    # non-negotiable #8, db/models/historical.py's module docstring) that
    # never reads raw_* tables and is never gated by pit/asof.py's
    # ingested_at-based cutoff by design -- its own real-world-timeline
    # availability policy (historical/availability.py) is the correct
    # leakage gate for this data instead. Exempted here rather than
    # relying on files in this package to avoid ever mentioning a Raw*
    # class name in a comment (e.g. explaining what a live equivalent
    # does), which would otherwise trip this heuristic as a false
    # positive.
    "historical",
)

SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key ID"),
    (
        re.compile(r"-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----"),
        "private key block",
    ),
    (re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"), "Slack token"),
    (
        re.compile(
            r"""(?i)\b(api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*["']([^"'\s]{12,})["']"""
        ),
        "hardcoded credential-shaped assignment",
    ),
]
SECRET_SAFE_VALUE_HINTS = (
    "change-me",
    "change_me",
    "dev-only",
    "dev_only",
    "example",
    "placeholder",
    "xxxxxxxx",
    "your-",
    "your_",
    "<",  # e.g. <YOUR_KEY_HERE>
    "${",  # env var interpolation
)

SKIP_DECORATOR_RE = re.compile(r"@pytest\.mark\.skip(?:if)?\s*(?:\(([^)]*)\))?")
SKIP_CALL_RE = re.compile(r"\bpytest\.skip\s*\(([^)]*)\)")
XFAIL_MARKER_RE = re.compile(r"@pytest\.mark\.xfail")

MUTATION_RE = re.compile(
    r"""\b(update|delete)\s*\(\s*(?:sa\.)?(\w+)\)"""  # update(Model) / delete(Model)
    r"""|\.query\(\s*(\w+)\s*\)\s*\.(update|delete)\s*\("""  # .query(Model).update(/.delete(
    r"""|\b(UPDATE|DELETE\s+FROM)\s+(\w+)""",  # raw SQL
    re.IGNORECASE,
)


@dataclass
class Violation:
    path: Path
    line: int
    severity: str  # "BLOCK" or "WARN"
    check: str
    message: str

    def render(self) -> str:
        rel = _rel_posix(self.path) if self.path.is_absolute() else str(self.path)
        return f"[{self.severity}] {rel}:{self.line}: {self.check}: {self.message}"


def _iter_lines(path: Path) -> list[str]:
    try:
        return path.read_text(errors="replace").splitlines()
    except OSError:
        return []


# A file physically staged under REPO_ROOT/.guardrail_precheck/<rel> is
# treated, for every path-prefix rule below, as if it were <rel> itself.
# This lets the PreToolUse hook (scripts/pretool_guardrails_check.py)
# reconstruct a proposed Edit/Write's content, stage it at this mirrored
# path, and get exactly the same verdict the real file would get post-write
# -- without ever touching the real file. See that script for the write
# side; .guardrail_precheck/ is gitignored and always cleaned up after use.
PRECHECK_PREFIX = ".guardrail_precheck/"


def _rel_posix(path: Path) -> str:
    try:
        rel = path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        rel = path.as_posix()
    rel = rel.removeprefix(PRECHECK_PREFIX)
    return rel


def _in_any_dir(rel: str, dirs: tuple[str, ...]) -> bool:
    return any(f"/{d}/" in f"/{rel}" for d in dirs)


def _strip_comment(line: str) -> str:
    # crude but adequate: ignore a leading '#' comment for match purposes
    stripped = line.lstrip()
    return "" if stripped.startswith("#") else line


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_no_mutation_of_immutable_tables(path: Path) -> list[Violation]:
    rel = _rel_posix(path)
    if not rel.startswith("engine/src/") or _in_any_dir(rel, MUTATION_EXCLUDED_DIRS):
        return []
    violations = []
    for i, raw_line in enumerate(_iter_lines(path), start=1):
        line = _strip_comment(raw_line)
        m = MUTATION_RE.search(line)
        if not m:
            continue
        target = next(
            (
                g
                for g in m.groups()
                if g
                and g.lower().replace(" ", "") not in ("update", "delete", "deletefrom")
            ),
            None,
        )
        if not target:
            continue
        target_l = target.lower()
        # Exact match only (not substring): a short captured word like "a"
        # or "the" is a substring of almost every table/model name (e.g.
        # "a" in "raw_schedule_events"), which previously caused prose like
        # "update a player's name" in a docstring to false-positive.
        if any(target_l == tok.lower() for tok in IMMUTABLE_BLOCK_TOKENS):
            violations.append(
                Violation(
                    path,
                    i,
                    "BLOCK",
                    "no-mutation-of-immutable-tables",
                    "UPDATE/DELETE-shaped statement appears to target an append-only table "
                    "(raw_*/projections/grades/audit_events). See ADR 0001 and CLAUDE.md's "
                    "do-not-do list -- 'current' must be derived by query, never by mutation.",
                )
            )
    return violations


def check_no_box_score_outside_grading(path: Path) -> list[Violation]:
    rel = _rel_posix(path)
    if not rel.startswith("engine/src/"):
        return []
    if _in_any_dir(rel, BOX_SCORE_ALLOWED_DIRS) or _in_any_dir(rel, ("db/models",)):
        return []
    if not (
        _in_any_dir(rel, ("features",))
        or _in_any_dir(rel, ("models",))
        or _in_any_dir(rel, ("orchestration",))
        or "/decision/" in f"/{rel}"
    ):
        return []
    violations = []
    for i, raw_line in enumerate(_iter_lines(path), start=1):
        line = _strip_comment(raw_line)
        if any(tok in line for tok in BOX_SCORE_TOKENS):
            violations.append(
                Violation(
                    path,
                    i,
                    "BLOCK",
                    "no-box-score-in-features-or-models",
                    "raw_final_box_scores / RawFinalBoxScore referenced outside grading/. "
                    "Outcome data must never reach feature or model code -- see ADR 0001.",
                )
            )
    return violations


def check_migration_not_modified(path: Path) -> list[Violation]:
    rel = _rel_posix(path)
    if "db/migrations/versions/" not in rel:
        return []
    status = _git_status_code(path)
    if status == "M":
        return [
            Violation(
                path,
                1,
                "BLOCK",
                "no-migration-tampering",
                "An already-committed migration file is being modified. Applied migrations are "
                "immutable history -- write a new migration instead of editing this one.",
            )
        ]
    return []


def check_no_disabled_tests(path: Path) -> list[Violation]:
    rel = _rel_posix(path)
    if "/tests/" not in f"/{rel}" or not rel.endswith(".py"):
        return []
    if rel in SELF_TEST_EXEMPT_PATHS:
        return []
    violations = []
    for i, raw_line in enumerate(_iter_lines(path), start=1):
        skip_m = SKIP_DECORATOR_RE.search(raw_line) or SKIP_CALL_RE.search(raw_line)
        if skip_m:
            args = skip_m.group(1) or ""
            severity = (
                "WARN" if "reason=" in args or '"' in args or "'" in args else "BLOCK"
            )
            violations.append(
                Violation(
                    path,
                    i,
                    severity,
                    "no-disabled-tests",
                    "Test skip marker found"
                    + (
                        ""
                        if severity == "WARN"
                        else " with no reason -- add reason= or remove it"
                    )
                    + ". Skipped tests hide real coverage gaps.",
                )
            )
        if XFAIL_MARKER_RE.search(raw_line):
            violations.append(
                Violation(
                    path,
                    i,
                    "WARN",
                    "no-disabled-tests",
                    "xfail marker found -- confirm this is intentional.",
                )
            )
    # best-effort deleted-test detection: fewer `def test_` than the committed version
    if _git_status_code(path) == "M":
        before = _git_show_head(path)
        if before is not None:
            before_count = len(re.findall(r"^\s*def test_", before, re.MULTILINE))
            after_count = len(
                re.findall(r"^\s*def test_", "\n".join(_iter_lines(path)), re.MULTILINE)
            )
            if after_count < before_count:
                violations.append(
                    Violation(
                        path,
                        1,
                        "WARN",
                        "no-disabled-tests",
                        f"Test count dropped ({before_count} -> {after_count}) vs. the committed version. "
                        "Confirm no test was silently deleted rather than intentionally refactored.",
                    )
                )
    return violations


def check_no_hardcoded_secrets(path: Path) -> list[Violation]:
    rel = _rel_posix(path)
    if rel in ("engine/.env.example", ".env.example") or rel.endswith(".lock"):
        return []
    if "/tests/fixtures/" in f"/{rel}":
        return []
    if rel in SELF_TEST_EXEMPT_PATHS:
        return []
    violations = []
    for i, raw_line in enumerate(_iter_lines(path), start=1):
        for pattern, label in SECRET_PATTERNS:
            m = pattern.search(raw_line)
            if not m:
                continue
            value = m.group(0)
            if any(hint in value.lower() for hint in SECRET_SAFE_VALUE_HINTS):
                continue
            violations.append(
                Violation(
                    path,
                    i,
                    "BLOCK",
                    "no-hardcoded-secrets",
                    f"Looks like a {label}. If this is a placeholder, use an obvious dev/example value.",
                )
            )
    return violations


def check_publication_cutoff_awareness(path: Path) -> list[Violation]:
    rel = _rel_posix(path)
    if not (_in_any_dir(rel, ("ledger",)) or "/api/routers/" in f"/{rel}"):
        return []
    text = "\n".join(_iter_lines(path))
    if "published_at" in text and "is_late_publication" not in text:
        return [
            Violation(
                path,
                1,
                "WARN",
                "publication-cutoff-rule",
                "published_at is set/used here without any reference to is_late_publication. "
                "Confirm the publication-cutoff rule (ADR 0008) is applied.",
            )
        ]
    return []


def check_asof_cutoff_enforcement(path: Path) -> list[Violation]:
    rel = _rel_posix(path)
    if not rel.startswith("engine/src/") or _in_any_dir(rel, ASOF_ALLOWED_DIRS):
        return []
    text = "\n".join(_iter_lines(path))
    if not any(name in text for name in RAW_MODEL_NAMES):
        return []
    if "ingested_at" in text and "observed_at" in text:
        return []
    return [
        Violation(
            Path(path),
            1,
            "WARN",
            "asof-cutoff-enforcement",
            "This file queries a raw_* model but doesn't reference both ingested_at and "
            "observed_at. Historical/point-in-time reads should go through pit/asof.py "
            "(ADR 0001) rather than querying raw tables directly.",
        )
    ]


CHECKS = [
    check_no_mutation_of_immutable_tables,
    check_no_box_score_outside_grading,
    check_migration_not_modified,
    check_no_disabled_tests,
    check_no_hardcoded_secrets,
    check_publication_cutoff_awareness,
    check_asof_cutoff_enforcement,
]


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _run_git(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def _git_status_code(path: Path) -> str | None:
    rel = _rel_posix(path)
    out = _run_git(["status", "--porcelain", "--", rel])
    if not out:
        return None
    code = out[:2].strip()
    return "M" if "M" in code else ("A" if "A" in code or "?" in code else code or None)


def _git_show_head(path: Path) -> str | None:
    rel = _rel_posix(path)
    return _run_git(["show", f"HEAD:{rel}"])


def _tracked_files() -> list[Path]:
    out = _run_git(["ls-files"]) or ""
    return [REPO_ROOT / line for line in out.splitlines() if line.endswith(".py")]


def _staged_files() -> list[Path]:
    out = _run_git(["diff", "--cached", "--name-only", "--diff-filter=ACM"]) or ""
    return [REPO_ROOT / line for line in out.splitlines() if line.endswith(".py")]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    if "--staged" in argv:
        files = _staged_files()
    elif len(argv) > 0:
        files = [Path(a).resolve() for a in argv]
    else:
        files = _tracked_files()

    files = [f for f in files if f.exists() and f.suffix == ".py"]

    violations: list[Violation] = []
    for f in files:
        for check in CHECKS:
            violations.extend(check(f))

    blocks = [v for v in violations if v.severity == "BLOCK"]
    warns = [v for v in violations if v.severity == "WARN"]

    for v in blocks + warns:
        print(v.render())

    print(
        f"\nguardrails: {len(blocks)} blocking, {len(warns)} warning ({len(files)} files checked)"
    )
    return 1 if blocks else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
