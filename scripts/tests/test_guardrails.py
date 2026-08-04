"""Regression tests for scripts/guardrails.py.

These write real fixture files *inside* the repo tree (under a throwaway
`engine/src/cassandra/_guardrail_fixtures/` directory, cleaned up after each
test) rather than in an unrelated tmp directory, because several checks key
off repo-relative paths (e.g. "engine/src/" prefix, ADR-allowed
subdirectories). Testing against paths outside the repo silently short-
circuits every check -- this bit the guardrails script itself during manual
testing, so it's pinned here.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import guardrails

REPO_ROOT = guardrails.REPO_ROOT
FIXTURE_ROOT = REPO_ROOT / "engine" / "src" / "cassandra" / "_guardrail_fixtures"


def _write(rel_path: str, content: str) -> Path:
    path = FIXTURE_ROOT / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def setup_function() -> None:
    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)


def teardown_function() -> None:
    shutil.rmtree(FIXTURE_ROOT, ignore_errors=True)


def _severities(path: Path) -> list[str]:
    violations = []
    for check in guardrails.CHECKS:
        violations.extend(check(path))
    return [v.severity for v in violations]


def _checks(path: Path) -> list[str]:
    violations = []
    for check in guardrails.CHECKS:
        violations.extend(check(path))
    return [v.check for v in violations]


def test_orm_update_on_projection_is_blocked():
    path = _write(
        "ledger/bad_update.py",
        "from sqlalchemy import update\n"
        "from cassandra.db.models.projection import Projection\n\n"
        "def bad():\n"
        '    session.execute(update(Projection).values(decision="OVER"))\n',
    )
    assert "no-mutation-of-immutable-tables" in _checks(path)
    assert "BLOCK" in _severities(path)


def test_raw_sql_delete_on_raw_table_is_blocked():
    path = _write(
        "ledger/bad_raw_sql.py",
        'def bad():\n    session.execute("DELETE FROM raw_lines WHERE line = 5.5")\n',
    )
    assert "no-mutation-of-immutable-tables" in _checks(path)


def test_english_prose_using_update_or_delete_is_not_flagged():
    # Regression: a docstring like "it's fine to update a player's name"
    # previously false-positived because the captured word "a" is a
    # substring of nearly every table name (e.g. "a" in "raw_lines").
    # Real code discussion of updating something must not trip this check.
    path = _write(
        "identity_like.py",
        '"""\n'
        "It's fine to update a player's name over time here since this is\n"
        "current identity, not a point-in-time fact. We never delete the row.\n"
        '"""\n',
    )
    assert "no-mutation-of-immutable-tables" not in _checks(path)


def test_insert_is_not_flagged_as_mutation():
    path = _write(
        "grading/service.py",
        "from cassandra.db.models.grading import Grade\n\n"
        'def append_grade():\n    session.add(Grade(result="WIN"))\n',
    )
    assert "no-mutation-of-immutable-tables" not in _checks(path)


def test_box_score_referenced_in_features_is_blocked():
    path = _write(
        "features/leaky.py",
        "from cassandra.db.models.raw import RawFinalBoxScore\n\ndef leak():\n    return RawFinalBoxScore\n",
    )
    checks = _checks(path)
    assert "no-box-score-in-features-or-models" in checks


def test_box_score_referenced_in_grading_is_allowed():
    path = _write(
        "grading/service.py",
        "from cassandra.db.models.raw import RawFinalBoxScore\n\ndef grade():\n    return RawFinalBoxScore\n",
    )
    assert "no-box-score-in-features-or-models" not in _checks(path)


def test_bare_skip_marker_is_blocked():
    # checked path must be under a "/tests/" directory for the check to apply
    path = REPO_ROOT / "engine" / "tests" / "unit" / "_guardrail_fixture_bare_skip.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "import pytest\n\n@pytest.mark.skip\ndef test_x():\n    assert True\n"
    )
    try:
        violations = []
        for check in guardrails.CHECKS:
            violations.extend(check(path))
        blocking = [
            v
            for v in violations
            if v.severity == "BLOCK" and v.check == "no-disabled-tests"
        ]
        assert blocking, violations
    finally:
        path.unlink(missing_ok=True)


def test_skip_with_reason_is_warn_not_block():
    path = (
        REPO_ROOT / "engine" / "tests" / "unit" / "_guardrail_fixture_reasoned_skip.py"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'import pytest\n\n@pytest.mark.skip(reason="flaky, see issue #12")\ndef test_x():\n    assert True\n'
    )
    try:
        violations = []
        for check in guardrails.CHECKS:
            violations.extend(check(path))
        relevant = [v for v in violations if v.check == "no-disabled-tests"]
        assert relevant and all(v.severity == "WARN" for v in relevant)
    finally:
        path.unlink(missing_ok=True)


def test_hardcoded_secret_is_blocked():
    path = _write("config_secret.py", 'api_key = "sk_live_abcdef0123456789ZZ"\n')
    assert "no-hardcoded-secrets" in _checks(path)


def test_placeholder_secret_value_is_allowed():
    path = _write("config_ok.py", 'admin_shared_secret = "change-me-dev-only"\n')
    assert "no-hardcoded-secrets" not in _checks(path)


def test_env_example_is_exempt_from_secret_scan():
    path = REPO_ROOT / ".env.example"
    assert path.exists(), "expected repo root .env.example to exist"
    assert "no-hardcoded-secrets" not in _checks(path)


def test_asof_cutoff_warns_when_raw_model_used_without_timestamps():
    path = _write(
        "some_module/uses_raw.py",
        "from cassandra.db.models.raw import RawLine\n\ndef f():\n    return RawLine\n",
    )
    checks = _checks(path)
    assert "asof-cutoff-enforcement" in checks


def test_asof_cutoff_silent_when_pit_module():
    path = _write(
        "pit/asof.py",
        "from cassandra.db.models.raw import RawLine\n\n"
        "def latest_as_of():\n    return RawLine  # ingested_at observed_at\n",
    )
    assert "asof-cutoff-enforcement" not in _checks(path)


def test_clean_file_has_no_violations():
    path = _write(
        "clean/module.py", "def add(a: int, b: int) -> int:\n    return a + b\n"
    )
    assert _checks(path) == []


def test_migration_modification_is_blocked_when_tracked(monkeypatch):
    fake_path = FIXTURE_ROOT / "db" / "migrations" / "versions" / "0001_init.py"

    def fake_status(path):
        return "M"

    monkeypatch.setattr(guardrails, "_git_status_code", fake_status)
    fake_path.parent.mkdir(parents=True, exist_ok=True)
    fake_path.write_text("# migration\n")
    try:
        violations = guardrails.check_migration_not_modified(fake_path)
        assert violations and violations[0].severity == "BLOCK"
    finally:
        fake_path.unlink(missing_ok=True)


def test_new_migration_file_is_not_blocked(monkeypatch):
    fake_path = FIXTURE_ROOT / "db" / "migrations" / "versions" / "0002_new.py"

    monkeypatch.setattr(guardrails, "_git_status_code", lambda path: "A")
    fake_path.parent.mkdir(parents=True, exist_ok=True)
    fake_path.write_text("# migration\n")
    try:
        assert guardrails.check_migration_not_modified(fake_path) == []
    finally:
        fake_path.unlink(missing_ok=True)


def test_main_exits_nonzero_only_on_block(capsys):
    clean = _write("clean2/module.py", "x = 1\n")
    assert guardrails.main([str(clean)]) == 0

    dirty = _write(
        "ledger/bad2.py", "session.execute(update(Projection).values(x=1))\n"
    )
    _write("ledger/__init__.py", "")
    assert guardrails.main([str(dirty)]) == 1


def test_this_test_file_itself_is_exempt_and_clean():
    # This file's fixture strings deliberately contain example secrets and
    # skip markers (to prove the checks above catch them) -- confirm the
    # SELF_TEST_EXEMPT_PATHS carve-out actually keeps guardrails.py from
    # flagging its own test suite when run for real (e.g. `make guardrails`,
    # or a git-staged check before commit).
    this_file = Path(__file__).resolve()
    assert guardrails._rel_posix(this_file) in guardrails.SELF_TEST_EXEMPT_PATHS
    violations = []
    for check in guardrails.CHECKS:
        violations.extend(check(this_file))
    blocking = [v for v in violations if v.severity == "BLOCK"]
    assert blocking == [], blocking
