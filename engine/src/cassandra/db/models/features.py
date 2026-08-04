"""Feature storage. A JSONB blob of named features per (snapshot, player,
game) rather than a rigid column-per-feature table -- deliberately, since
the model family and feature set are still evolving (handbook non-negotiable
#7: don't preselect the model). See features/registry.py (Phase 3) for the
documented feature names this blob is expected to contain.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cassandra.db.base import Base


class FeatureSet(Base):
    __tablename__ = "feature_sets"

    feature_set_version: Mapped[str] = mapped_column(String, primary_key=True)
    description: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FeatureValue(Base):
    __tablename__ = "feature_values"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("snapshots.snapshot_id"))
    player_id: Mapped[str] = mapped_column(String, nullable=False)
    game_id: Mapped[str] = mapped_column(String, nullable=False)
    feature_set_version: Mapped[str] = mapped_column(
        String, ForeignKey("feature_sets.feature_set_version"), nullable=False
    )
    features: Mapped[dict] = mapped_column(JSONB, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
