"""Central configuration.

Timestamp convention (ADR 0009): every timestamp stored and passed around
inside the engine is UTC (`timestamptz` columns, timezone-aware
`datetime` objects). `OPERATING_TIMEZONE` is used *only* to derive a
calendar `slate_date` from a game's UTC start time -- it is never used to
alter how timestamps are stored, compared, or filtered.
"""

from __future__ import annotations

import subprocess
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://cassandra:cassandra_dev_only@localhost:5432/cassandra"

    # ADR 0009 -- calendar-day bucketing only, never used for storage/comparison.
    operating_timezone: str = "America/New_York"

    # ADR 0005 -- provisional, not a calibrated or business-approved value.
    decision_edge_threshold: float = 0.05

    # ADR 0011 -- demo-only auth, not production-ready.
    admin_shared_secret: str = "change-me-dev-only"

    # ADR 0010 -- baked in at deploy time (e.g. Replit build step) when
    # there's no .git directory to introspect; falls back to `git
    # rev-parse HEAD` for local/dev runs. See get_git_commit_sha().
    git_commit_sha: str | None = None


settings = Settings()


@lru_cache(maxsize=1)
def get_git_commit_sha() -> str | None:
    """The engine's running commit, for ADR 0010's reproducibility hash.
    Prefers an explicitly configured GIT_COMMIT_SHA (set at deploy time,
    e.g. on Replit where there may be no .git directory); falls back to
    `git rev-parse HEAD` for local/dev runs. Returns None (never raises)
    if neither is available -- a missing commit SHA is a visible gap in
    the reproducibility record, not a crash."""
    if settings.git_commit_sha:
        return settings.git_commit_sha
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def operating_tz() -> ZoneInfo:
    return ZoneInfo(settings.operating_timezone)


def slate_date_for(scheduled_start_utc: datetime) -> date:
    """The single source of truth for 'which slate does this game belong to'.

    ADR 0009: convert a game's UTC start time into the operating timezone
    and take that local calendar date. Do not re-derive slate_date any
    other way elsewhere in the codebase.
    """
    if scheduled_start_utc.tzinfo is None:
        raise ValueError("scheduled_start_utc must be timezone-aware (UTC)")
    return scheduled_start_utc.astimezone(operating_tz()).date()
