"""Pipeline run tracking -- drives the Admin stage tracker and is the
authority the Phase 4 action-endpoint state guards (ADR 0007) check
against."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from cassandra.db.base import Base

RUN_STATUSES = ("running", "succeeded", "failed")
STAGES = ("INGEST", "VALIDATE", "FREEZE", "PROJECT", "REVIEW", "PUBLISH", "GRADE")
STAGE_STATUSES = ("pending", "running", "succeeded", "failed", "skipped")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (CheckConstraint(f"status IN {RUN_STATUSES}", name="ck_pipeline_runs_status"),)

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    slate_date: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    current_stage: Mapped[str | None] = mapped_column(String)


class PipelineRunStage(Base):
    __tablename__ = "pipeline_run_stages"
    __table_args__ = (
        CheckConstraint(f"stage IN {STAGES}", name="ck_pipeline_run_stages_stage"),
        CheckConstraint(f"status IN {STAGE_STATUSES}", name="ck_pipeline_run_stages_status"),
    )

    run_id: Mapped[str] = mapped_column(String, ForeignKey("pipeline_runs.run_id"), primary_key=True)
    stage: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[str | None] = mapped_column(String)
