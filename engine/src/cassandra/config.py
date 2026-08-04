"""Central configuration.

Timestamp convention (ADR 0009): every timestamp stored and passed around
inside the engine is UTC (`timestamptz` columns, timezone-aware
`datetime` objects). `OPERATING_TIMEZONE` is used *only* to derive a
calendar `slate_date` from a game's UTC start time -- it is never used to
alter how timestamps are stored, compared, or filtered.
"""

from __future__ import annotations

from datetime import date, datetime
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


settings = Settings()


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
