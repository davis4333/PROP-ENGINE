"""Append-only grading. A correction inserts a new row with a later
graded_at; "current" grade = latest graded_at per projection_id. Old grade
rows (including old losses) always stay queryable -- see ADR 0007 (grade
requires PUBLISH succeeded + game Final) for when a grade write is allowed.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cassandra.db.base import Base

GRADE_RESULTS = ("WIN", "LOSS", "PUSH", "VOID", "NO_PLAY")


class Grade(Base):
    __tablename__ = "grades"
    __table_args__ = (CheckConstraint(f"result IN {GRADE_RESULTS}", name="ck_grades_result"),)

    grade_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    projection_id: Mapped[str] = mapped_column(
        String, ForeignKey("projections.projection_id"), nullable=False
    )
    graded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result: Mapped[str] = mapped_column(String, nullable=False)
    actual_strikeouts: Mapped[int | None] = mapped_column(Integer)
    final_box_score_raw_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_final_box_scores.raw_id")
    )
    detail: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
