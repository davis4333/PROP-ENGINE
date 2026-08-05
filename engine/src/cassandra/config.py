"""Central configuration.

Timestamp convention (ADR 0009): every timestamp stored and passed around
inside the engine is UTC (`timestamptz` columns, timezone-aware
`datetime` objects). `OPERATING_TIMEZONE` is used *only* to derive a
calendar `slate_date` from a game's UTC start time -- it is never used to
alter how timestamps are stored, compared, or filtered.
"""

from __future__ import annotations

import subprocess  # nosec B404 -- only used below with a fixed argv, no shell
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://cassandra:cassandra_dev_only@localhost:5432/cassandra"

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url_scheme(cls, value: str) -> str:
        """Managed Postgres providers (Neon, Supabase, Replit's own Postgres
        integration, Heroku-style hosts) hand out "postgresql://" or
        "postgres://" connection strings. SQLAlchemy needs the psycopg3
        driver named explicitly ("postgresql+psycopg://") or it falls back
        to psycopg2, which this project doesn't install. Rewriting the
        scheme here means any of those connection strings can be pasted in
        as-is, rather than requiring a manual edit every deploy."""
        if value.startswith("postgresql+"):
            return value
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value[len("postgresql://") :]
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value[len("postgres://") :]
        return value

    # ADR 0009 -- calendar-day bucketing only, never used for storage/comparison.
    operating_timezone: str = "America/New_York"

    # ADR 0005 -- provisional, not a calibrated or business-approved value.
    decision_edge_threshold: float = 0.05

    # ADR 0011 -- demo-only auth, not production-ready.
    admin_shared_secret: str = "change-me-dev-only"

    # orchestration/scheduler.py -- a long-running deployment (e.g. Replit)
    # populates Today and grades recent slates on its own rather than
    # requiring a human to run the CLI by hand every day. Off by default
    # for local/dev and CI runs (an engine imported for one-off CLI/test
    # use shouldn't silently start hitting the live MLB API in the
    # background); scripts/replit_start.sh sets this to true. Also
    # settable via docker-compose.yml's passthrough (defaults to false
    # there too).
    auto_scheduler_enabled: bool = False
    # Local hour (in operating_timezone, 0-23) after which the daily
    # run_slate() fires, once per day. Grading is re-attempted on every
    # scheduler tick regardless of this hour -- see scheduler.py's
    # docstring for why the two have different cadences.
    auto_run_hour_local: int = 7

    # adapters/lines_odds_api.py -- a real, licensed odds vendor (The Odds
    # API), used in place of adapters/lines_manual.py's manual drop-folder
    # stand-in when configured. NOT Underdog's own DFS pick'em lines --
    # real regulated-sportsbook strikeout totals (see the adapter's
    # docstring and CURRENT_STATE_AUDIT.md's Provisional section).
    # None (unset) means "use the manual/fixture adapter instead" --
    # orchestration/run_slate.py's _ingest_lines() branches on this.
    odds_api_key: str | None = None

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
        # Fixed argv, no shell, no untrusted input -- not the command
        # injection / partial-path risk bandit's B603/B607 generically
        # flag subprocess calls for.
        result = subprocess.run(  # nosec B603 B607
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
