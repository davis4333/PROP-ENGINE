"""Source registry: every adapter must be registered here (kind, ownership,
version) before it can write to a raw_* table. See adapters/base.py for the
adapter contract these rows describe.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from cassandra.db.base import Base

SOURCE_KINDS = ("schedule", "pitcher_stats", "weather", "park", "umpire", "lines")

# SourceHealth.last_status vocabulary. `last_status` stays a free-text
# String column (no CHECK constraint) rather than gaining a migration --
# these are the only values ingestion/ingest_service.py's
# _update_source_health() actually writes.
#   HEALTHY         -- last fetch succeeded.
#   PENDING         -- expected, temporary absence (e.g. a box score
#                       before the game is Final, a prop market that
#                       hasn't posted yet) -- never a blocking issue.
#   DEGRADED        -- a real fetch error (HTTP 5xx, timeout, etc.), but
#                       still within the first few consecutive failures --
#                       worth watching, not yet worth alarming on.
#   FAILED          -- a real fetch error that has now failed
#                       CONSECUTIVE_FAILURE_ALERT_THRESHOLD+ times in a
#                       row (api/routers/admin.py) -- this is what
#                       actually surfaces as a blocking issue.
#   DISABLED        -- permanently unavailable by design (e.g.
#                       umpire_stub -- no reliable free source exists at
#                       all) -- never a blocking issue, and never
#                       expected to recover on its own.
#   QUOTA_LIMITED   -- a real vendor rate/quota limit (HTTP 429)
#                       specifically, distinct from a generic upstream
#                       error since the fix (wait for quota, or upgrade
#                       plan) is different from "something is broken."
SOURCE_HEALTH_STATES = ("HEALTHY", "PENDING", "DEGRADED", "FAILED", "DISABLED", "QUOTA_LIMITED")


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (CheckConstraint(f"kind IN {SOURCE_KINDS}", name="ck_sources_kind"),)

    source_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    adapter_version: Mapped[str | None] = mapped_column(String)
    base_url: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceHealth(Base):
    __tablename__ = "source_health"

    source_id: Mapped[str] = mapped_column(String, primary_key=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
