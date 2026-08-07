"""Central configuration.

Timestamp convention (ADR 0009): every timestamp stored and passed around
inside the engine is UTC (`timestamptz` columns, timezone-aware
`datetime` objects). `OPERATING_TIMEZONE` is used *only* to derive a
calendar `slate_date` from a game's UTC start time -- it is never used to
alter how timestamps are stored, compared, or filtered.
"""

from __future__ import annotations

import os
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

    # ADR 0008 -- how close to a game's scheduled first pitch a
    # publication must land to still count as "official" (excluded from
    # official aggregates/is_late_publication=True once inside this
    # window). 15 is the mission directive's own suggested working
    # default, not a calibrated or Tyler-confirmed operational number --
    # same "provisional, configurable, not silently final" status as
    # decision_edge_threshold above; ADR 0008 explicitly leaves the real
    # number open pending Tyler's input.
    publication_freeze_minutes_before_first_pitch: int = 15

    # ADR 0011 -- demo-only auth, not production-ready.
    admin_shared_secret: str = "change-me-dev-only"

    # Phase 8 security hardening. "*" (unrestricted) is the existing,
    # unchanged default -- safe in the actual Replit deployment topology
    # (the engine binds 127.0.0.1-only there; scripts/replit_start.sh),
    # but a real non-Replit/non-proxied deployment (e.g. docker-compose
    # with the engine's own port exposed) should set this to a comma-
    # separated allowlist of real frontend origins via the
    # ALLOWED_ORIGINS env var. Kept permissive by default rather than
    # guessing a real production origin this build doesn't know.
    allowed_origins: str = "*"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    # Explicit override for "is this a real production deployment" --
    # see is_production_environment() below. Most deployments shouldn't
    # need to set this: Replit's own REPLIT_DEPLOYMENT env var (present
    # only on a published deployment, never the interactive workspace or
    # local/CI runs) is detected automatically.
    production_mode: bool = False

    # orchestration/scheduler.py -- a long-running deployment (e.g. Replit)
    # populates Today and grades recent slates on its own rather than
    # requiring a human to run the CLI by hand every day. Off by default
    # for local/dev and CI runs (an engine imported for one-off CLI/test
    # use shouldn't silently start hitting the live MLB API in the
    # background); scripts/replit_start.sh sets this to true. Also
    # settable via docker-compose.yml's passthrough (defaults to false
    # there too).
    auto_scheduler_enabled: bool = False
    # Comma-separated local hours (in operating_timezone, 0-23) at which
    # run_slate() fires -- e.g. "7,12,16" for a morning/midday/pre-
    # evening-game refresh, catching newly confirmed starters, updated
    # lines, and weather throughout the day rather than once at a single
    # fixed morning hour. Grading is re-attempted on every scheduler tick
    # regardless -- see scheduler.py's docstring for why the two have
    # different cadences. Parsed by orchestration/scheduler.py's
    # parse_run_hours(), which never raises on a malformed entry.
    auto_run_hours_local: str = "7,12,16"
    # orchestration/scheduler.py's background-thread poll interval and
    # how many trailing days grade_slate_run() is re-attempted for on
    # every tick. Previously hardcoded module constants -- pulled into
    # settings (Phase 2C) so a deployment can tune cadence without a code
    # change, matching auto_run_hours_local's existing configurability.
    scheduler_poll_interval_seconds: int = 15 * 60
    scheduler_grade_lookback_days: int = 3

    # orchestration/retraining_scheduler.py -- periodic, human-gated model
    # retraining (the "self-learning loop"). Off by default, same opt-in
    # posture as auto_scheduler_enabled -- an engine imported for local/
    # dev/CI/test use shouldn't silently start a backfill+train cycle in
    # the background. Runs on its own separate background thread/cadence
    # from auto_scheduler_enabled above, since a retrain attempt (backfill
    # + dataset build + walk-forward fit) is far heavier/slower than a
    # daily run_slate()/grade_slate_run() tick and must never delay those.
    # NEVER auto-promotes -- see registry/service.py's promote_to_active()
    # docstring; a human always reviews and promotes/rejects by hand.
    auto_retrain_enabled: bool = False
    # How often (days) a retrain attempt is due -- provisional default
    # (weekly), not a calibrated cadence; tunable without a code change.
    # Cadence is DB-derived (audit_events' latest "retrain_attempted" row),
    # not in-memory, matching auto_run_hours_local's restart-safety.
    retrain_interval_days: int = 7
    # How many trailing days of newly-Final games to backfill before
    # rebuilding the training dataset on each retrain attempt --
    # provisional default, generously overlaps retrain_interval_days so a
    # slow/late-completing game from a prior window is still caught.
    # historical/backfill.py's run_backfill() is idempotent/safe to
    # re-run for an overlapping range -- already-succeeded work items are
    # skipped, never redone.
    retrain_backfill_lookback_days: int = 14
    # First MLB season a rebuilt training dataset covers -- every season
    # from this one through the current year is included, so the dataset
    # keeps growing as more seasons complete without a code change.
    retrain_dataset_start_season: int = 2023

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

# Exact known placeholder/example values (from .env.example, this file's
# own default, and common generic defaults) -- checked case-insensitively.
# Not exhaustive by design: this catches values nobody could have chosen
# on purpose, not a strength policy. Combined with a minimum-length floor
# below to also catch short guessable secrets that aren't on this list.
_WEAK_ADMIN_SECRETS = {
    "",
    "test",
    "change-me-dev-only",
    "changeme",
    "change-me",
    "admin",
    "password",
    "secret",
}
_MIN_ADMIN_SECRET_LENGTH = 16


def is_production_environment() -> bool:
    """True for a real deployment (Phase 8's "production startup must
    reject weak secrets" gate), false for local/dev/CI. Prefers an
    explicit settings.production_mode override; otherwise detects
    Replit's own REPLIT_DEPLOYMENT env var, which Replit sets only on a
    published deployment -- never the interactive workspace, `docker-
    compose up`, or a test run."""
    return settings.production_mode or bool(os.environ.get("REPLIT_DEPLOYMENT"))


def admin_secret_is_weak(secret: str) -> bool:
    """Used both at startup (crash before serving traffic) and available
    for the Admin page to warn about, per Phase 8. Deliberately a
    standalone predicate rather than inlined so both call sites -- and
    tests -- share exactly one definition of "weak"."""
    return secret.strip().lower() in _WEAK_ADMIN_SECRETS or len(secret) < _MIN_ADMIN_SECRET_LENGTH


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
