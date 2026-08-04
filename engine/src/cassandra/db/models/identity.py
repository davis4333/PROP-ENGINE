"""Deterministic-identity tables: venues, teams, players, games.

These are the resolved/canonical entities that raw records get matched
against (see ENTITY_UNMATCHED in decision/reason_codes.py, Phase 3). They
are small reference tables, not append-only raw ingestion -- it's fine to
update a player's name/team over time here since this is *current*
identity, not a point-in-time fact. Point-in-time facts about these
entities (e.g. "who started this game") live in the raw_* tables.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from cassandra.db.base import Base


class Venue(Base):
    __tablename__ = "venues"

    venue_id: Mapped[str] = mapped_column(String, primary_key=True)
    mlb_venue_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    city: Mapped[str | None] = mapped_column(String)
    # Foreign key into raw_park_factors' natural key, resolved separately --
    # park factors are point-in-time facts (a factor can be recomputed
    # season to season), so they live in raw_park_factors, not here.
    park_factor_key: Mapped[str | None] = mapped_column(String)


class Team(Base):
    __tablename__ = "teams"

    team_id: Mapped[str] = mapped_column(String, primary_key=True)
    mlb_team_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    abbreviation: Mapped[str | None] = mapped_column(String)


class Player(Base):
    __tablename__ = "players"

    player_id: Mapped[str] = mapped_column(String, primary_key=True)
    mlb_person_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    bats: Mapped[str | None] = mapped_column(String)
    throws: Mapped[str | None] = mapped_column(String)


class Game(Base):
    __tablename__ = "games"

    game_id: Mapped[str] = mapped_column(String, primary_key=True)
    mlb_game_pk: Mapped[int | None] = mapped_column(Integer, unique=True)
    game_date: Mapped[datetime] = mapped_column(DateTime(timezone=False))  # calendar date only
    scheduled_start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    home_team_id: Mapped[str | None] = mapped_column(String)
    away_team_id: Mapped[str | None] = mapped_column(String)
    venue_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
