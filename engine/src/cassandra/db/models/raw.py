"""Raw immutable ingestion tables (ADR 0001).

Every table here follows the same discipline:
  - `observed_at`: the source's claimed effective/as-of time for the fact.
  - `ingested_at`: when *this system* physically wrote the row -- the true
    leakage gate (see pit/asof.py).
  - Rows are INSERT-only. The initial Alembic migration REVOKEs UPDATE and
    DELETE on these tables for the application DB role -- see
    db/migrations/versions and CLAUDE.md's do-not-do list.

`raw_final_box_scores` is the one exception to "these tables feed the
snapshot builder": it must never be read by pit/asof.py, features/, or
models/ -- only grading/ may query it, and only for game_status='Final'
rows. That structural exclusion is enforced by code review / CLAUDE.md,
not by a DB grant (grading legitimately needs SELECT too).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cassandra.db.base import Base


def _raw_id_col() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class RawScheduleEvent(Base):
    __tablename__ = "raw_schedule_events"

    raw_id: Mapped[uuid.UUID] = _raw_id_col()
    source_id: Mapped[str] = mapped_column(String, ForeignKey("sources.source_id"), nullable=False)
    mlb_game_pk: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    record_hash: Mapped[str | None] = mapped_column(String)

    __table_args__ = (Index("ix_raw_schedule_events_pk_ingested", "mlb_game_pk", "ingested_at"),)


class RawProbablePitcher(Base):
    __tablename__ = "raw_probable_pitchers"

    raw_id: Mapped[uuid.UUID] = _raw_id_col()
    source_id: Mapped[str] = mapped_column(String, ForeignKey("sources.source_id"), nullable=False)
    mlb_game_pk: Mapped[int] = mapped_column(Integer, nullable=False)
    player_mlb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    team_mlb_id: Mapped[int | None] = mapped_column(Integer)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    record_hash: Mapped[str | None] = mapped_column(String)

    __table_args__ = (Index("ix_raw_probable_pitchers_pk_ingested", "mlb_game_pk", "ingested_at"),)


class RawLineup(Base):
    __tablename__ = "raw_lineups"

    raw_id: Mapped[uuid.UUID] = _raw_id_col()
    source_id: Mapped[str] = mapped_column(String, ForeignKey("sources.source_id"), nullable=False)
    mlb_game_pk: Mapped[int] = mapped_column(Integer, nullable=False)
    team_mlb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    batting_order: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (Index("ix_raw_lineups_pk_ingested", "mlb_game_pk", "ingested_at"),)


class RawPitcherGameLog(Base):
    __tablename__ = "raw_pitcher_game_logs"

    raw_id: Mapped[uuid.UUID] = _raw_id_col()
    source_id: Mapped[str] = mapped_column(String, ForeignKey("sources.source_id"), nullable=False)
    player_mlb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    mlb_game_pk: Mapped[int | None] = mapped_column(Integer)
    stat_date: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    batters_faced: Mapped[int | None] = mapped_column(Integer)
    strikeouts: Mapped[int | None] = mapped_column(Integer)
    pitch_count: Mapped[int | None] = mapped_column(Integer)
    innings_pitched: Mapped[float | None] = mapped_column(Numeric)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (Index("ix_raw_pitcher_game_logs_player_ingested", "player_mlb_id", "ingested_at"),)


class RawWeatherObservation(Base):
    __tablename__ = "raw_weather_observations"

    raw_id: Mapped[uuid.UUID] = _raw_id_col()
    source_id: Mapped[str] = mapped_column(String, ForeignKey("sources.source_id"), nullable=False)
    venue_id: Mapped[str] = mapped_column(String, nullable=False)
    forecast_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    temp_f: Mapped[float | None] = mapped_column(Numeric)
    wind_mph: Mapped[float | None] = mapped_column(Numeric)
    wind_dir: Mapped[str | None] = mapped_column(String)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (Index("ix_raw_weather_venue_ingested", "venue_id", "ingested_at"),)


class RawParkFactor(Base):
    __tablename__ = "raw_park_factors"

    raw_id: Mapped[uuid.UUID] = _raw_id_col()
    source_id: Mapped[str] = mapped_column(String, ForeignKey("sources.source_id"), nullable=False)
    venue_id: Mapped[str] = mapped_column(String, nullable=False)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    k_factor: Mapped[float] = mapped_column(Numeric, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        Index("ix_raw_park_factors_venue_season_ingested", "venue_id", "season", "ingested_at"),
    )


class RawUmpireAssignment(Base):
    __tablename__ = "raw_umpire_assignments"

    raw_id: Mapped[uuid.UUID] = _raw_id_col()
    source_id: Mapped[str] = mapped_column(String, ForeignKey("sources.source_id"), nullable=False)
    mlb_game_pk: Mapped[int] = mapped_column(Integer, nullable=False)
    umpire_name: Mapped[str | None] = mapped_column(String)
    is_available: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (Index("ix_raw_umpire_pk_ingested", "mlb_game_pk", "ingested_at"),)


class RawLine(Base):
    __tablename__ = "raw_lines"

    raw_id: Mapped[uuid.UUID] = _raw_id_col()
    source_id: Mapped[str] = mapped_column(String, ForeignKey("sources.source_id"), nullable=False)
    mlb_game_pk: Mapped[int] = mapped_column(Integer, nullable=False)
    player_mlb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    market: Mapped[str] = mapped_column(String, nullable=False, default="pitcher_strikeouts")
    line: Mapped[float] = mapped_column(Numeric, nullable=False)
    over_price: Mapped[float | None] = mapped_column(Numeric)
    under_price: Mapped[float | None] = mapped_column(Numeric)
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    record_hash: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        Index("ix_raw_lines_pk_player_ingested", "mlb_game_pk", "player_mlb_id", "ingested_at"),
    )


class RawFinalBoxScore(Base):
    """Outcome data. NEVER read from pit/asof.py, features/, or models/ --
    only grading/, and only where game_status='Final'. See module docstring
    and ADR 0001."""

    __tablename__ = "raw_final_box_scores"

    raw_id: Mapped[uuid.UUID] = _raw_id_col()
    source_id: Mapped[str] = mapped_column(String, ForeignKey("sources.source_id"), nullable=False)
    mlb_game_pk: Mapped[int] = mapped_column(Integer, nullable=False)
    player_mlb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    strikeouts_recorded: Mapped[int | None] = mapped_column(Integer)
    innings_pitched: Mapped[float | None] = mapped_column(Numeric)
    pitch_count: Mapped[int | None] = mapped_column(Integer)
    game_status: Mapped[str] = mapped_column(String, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        Index("ix_raw_final_box_scores_pk_player_ingested", "mlb_game_pk", "player_mlb_id", "ingested_at"),
    )
