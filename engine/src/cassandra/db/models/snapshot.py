"""Point-in-time snapshots (ADR 0001).

A snapshot freezes a `(slate_date, cutoff_at)` view of the raw tables.
`snapshot_raw_refs` records exactly which raw rows fed it -- the audit
trail. Because raw rows are never deleted, anything NOT referenced by a
snapshot's refs is, by omission, documented as excluded-by-cutoff --
there is no separate "excluded" table to maintain.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cassandra.db.base import Base

SNAPSHOT_STATUSES = ("building", "frozen", "failed")
DQ_STATUSES = ("pass", "fail", "warn")


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = (CheckConstraint(f"status IN {SNAPSHOT_STATUSES}", name="ck_snapshots_status"),)

    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slate_date: Mapped[date] = mapped_column(Date, nullable=False)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String, nullable=False, default="building")
    notes: Mapped[str | None] = mapped_column(String)


class SnapshotRawRef(Base):
    __tablename__ = "snapshot_raw_refs"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("snapshots.snapshot_id"), primary_key=True
    )
    raw_table: Mapped[str] = mapped_column(String, primary_key=True)
    raw_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    natural_key: Mapped[str | None] = mapped_column(String)


class SnapshotDataQuality(Base):
    __tablename__ = "snapshot_data_quality"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("snapshots.snapshot_id"))
    check_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String)
    detail: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (CheckConstraint(f"status IN {DQ_STATUSES}", name="ck_snapshot_dq_status"),)
