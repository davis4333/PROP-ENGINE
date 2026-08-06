"""Historical backfill tracking + the dedicated historical-reconstruction
data tables (docs/HISTORICAL_BACKFILL_DESIGN.md).

Deliberately separate from db/models/raw.py's live raw_* tables, not an
extension of them, for one structural reason: `pit/asof.py`'s
`latest_as_of`/`all_as_of`/`latest_grouped_as_of` are the live pipeline's
sole leakage gate, and they operate over the raw_* tables by name. A
backfilled row's `ingested_at` is always "whenever the backfill actually
ran" (real, physically true -- never backdated, per
CLAUDE.md/docs/adr/0001), which for a 2023 game backfilled in 2026 would
make it permanently invisible to any as-of query with a pre-2026 cutoff.
That's correct for the live pipeline (nothing here can leak into it --
these tables are never named in pit/asof.py or read by
features/models/decision/, and pit/asof.py's own docstring lists exactly
which tables it operates over), but it also means these rows can't
reconstruct "what would Cassandra have known on date X" for training
purposes via the live as-of mechanism at all. That reconstruction needs
its own explicit availability policy based on the real world's own
timeline (a prior game's stats become eligible once that prior game
reached Final) -- see historical/availability.py and
docs/HISTORICAL_AVAILABILITY_POLICY.md -- deliberately not the live
ingested_at-based gate, so the live protections are never weakened to
accommodate backfilled data.

Idempotency here uses natural-key upsert (ON CONFLICT DO UPDATE), not the
raw_* tables' append-only/immutable discipline: CLAUDE.md's non-negotiable
#3 and the immutability migrations/triggers name exactly
raw_*/projections/grades/audit_events, not these tables, and upsert-by-
natural-key is the repository-consistent, safe mechanism the backfill
directive calls for ("rerunning a completed game must not corrupt data or
create uncontrolled duplicates").
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cassandra.db.base import Base

BACKFILL_RUN_STATUSES = ("running", "completed", "failed", "paused", "cancelled")
BACKFILL_ITEM_STATUSES = ("pending", "in_progress", "succeeded", "failed", "skipped")

# Every row this backfill writes is stamped with one of these -- explicit,
# queryable provenance per the directive's non-negotiable #3. LIVE_CAPTURED
# doesn't appear in this module (it's the default/only mode for the live
# raw_* tables, which don't need a column for a distinction that's always
# true) -- it's listed here only so callers referencing "capture mode"
# have one shared vocabulary to import from.
CAPTURE_MODE_LIVE_CAPTURED = "LIVE_CAPTURED"
CAPTURE_MODE_HISTORICAL_RECONSTRUCTED = "HISTORICAL_RECONSTRUCTED"
CAPTURE_MODE_HISTORICAL_ACTUAL = "HISTORICAL_ACTUAL"


class BackfillRun(Base):
    """One invocation of `cassandra backfill-mlb` (or a resumed
    continuation of one). Deliberately mutable/updatable, unlike the live
    raw_* tables -- this is operational job-tracking state, not an
    append-only fact ledger."""

    __tablename__ = "backfill_runs"

    backfill_run_id: Mapped[str] = mapped_column(String, primary_key=True)
    requested_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    requested_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    source: Mapped[str] = mapped_column(String, nullable=False)
    domain: Mapped[str] = mapped_column(String, nullable=False)
    season: Mapped[int | None] = mapped_column(Integer)
    current_cursor: Mapped[str | None] = mapped_column(String)
    total_work_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_work_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_work_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_work_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String)
    code_commit_sha: Mapped[str | None] = mapped_column(String)
    adapter_version: Mapped[str | None] = mapped_column(String)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    coverage_summary: Mapped[dict | None] = mapped_column(JSONB)


class BackfillItem(Base):
    """One unit of resumable/idempotent work (currently: one MLB game's
    worth of a given domain, e.g. domain="game_feed" work_key="717753").
    Uniqueness is global (not per-run) -- a later run resuming or retrying
    sees the same row and its real prior status, so "already succeeded"
    is a durable fact independent of which run first did the work."""

    __tablename__ = "backfill_items"
    __table_args__ = (
        UniqueConstraint("domain", "work_key", name="uq_backfill_items_domain_work_key"),
        Index("ix_backfill_items_run_status", "backfill_run_id", "status"),
    )

    backfill_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    backfill_run_id: Mapped[str] = mapped_column(String, ForeignKey("backfill_runs.backfill_run_id"))
    domain: Mapped[str] = mapped_column(String, nullable=False)
    work_key: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String)
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HistoricalPitcherStart(Base):
    """One pitcher's appearance in one historical game, reconstructed from
    MLB's final game feed (one feed call covers every pitcher in that
    game -- see historical/backfill.py). Covers both directive item 3
    (actual starters, `is_starter`) and item 4 (pitcher outcomes) as one
    row, since both come from the same feed payload.

    `pregame_starter_confirmation_captured` is always False here (backfill
    directive non-negotiable #6): a historical game's actual starter,
    identified from the box score after the fact, is explicitly NOT the
    same claim as a live pregame-confirmed probable pitcher
    (raw_probable_pitchers.is_confirmed) -- this column makes that
    distinction queryable rather than letting a joined/derived pipeline
    silently conflate the two.
    """

    __tablename__ = "historical_pitcher_starts"
    __table_args__ = (
        UniqueConstraint("mlb_game_pk", "player_mlb_id", name="uq_historical_pitcher_starts_game_player"),
        Index("ix_historical_pitcher_starts_player_date", "player_mlb_id", "game_date"),
    )

    historical_pitcher_start_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    mlb_game_pk: Mapped[int] = mapped_column(Integer, nullable=False)
    game_date: Mapped[date] = mapped_column(Date, nullable=False)
    player_mlb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    team_mlb_id: Mapped[int | None] = mapped_column(Integer)
    opponent_mlb_id: Mapped[int | None] = mapped_column(Integer)
    is_starter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pregame_starter_confirmation_captured: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    batters_faced: Mapped[int | None] = mapped_column(Integer)
    strikeouts: Mapped[int | None] = mapped_column(Integer)
    pitches_thrown: Mapped[int | None] = mapped_column(Integer)
    strikes: Mapped[int | None] = mapped_column(Integer)
    balls: Mapped[int | None] = mapped_column(Integer)
    hits_allowed: Mapped[int | None] = mapped_column(Integer)
    walks: Mapped[int | None] = mapped_column(Integer)
    hit_batters: Mapped[int | None] = mapped_column(Integer)
    home_runs_allowed: Mapped[int | None] = mapped_column(Integer)
    earned_runs: Mapped[int | None] = mapped_column(Integer)
    runs_allowed: Mapped[int | None] = mapped_column(Integer)
    outs_recorded: Mapped[int | None] = mapped_column(Integer)
    innings_pitched: Mapped[float | None] = mapped_column(Numeric)
    decision: Mapped[str | None] = mapped_column(String)
    game_status: Mapped[str] = mapped_column(String, nullable=False)
    capture_mode: Mapped[str] = mapped_column(
        String, nullable=False, default=CAPTURE_MODE_HISTORICAL_RECONSTRUCTED
    )
    source_id: Mapped[str] = mapped_column(String, ForeignKey("sources.source_id"), nullable=False)
    backfill_run_id: Mapped[str | None] = mapped_column(String, ForeignKey("backfill_runs.backfill_run_id"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    record_hash: Mapped[str | None] = mapped_column(String)


class HistoricalLineup(Base):
    """One batter's slot in one team's actual (post-hoc, box-score-derived)
    historical starting lineup. Labeled HISTORICAL_ACTUAL, never treated
    as a pregame-known lineup (directive non-negotiable #6) -- there is no
    trustworthy pregame-availability timestamp for this in the free MLB
    Stats API, so historical/availability.py's STRICT_LIVE_COMPATIBLE tier
    must exclude it unless that changes."""

    __tablename__ = "historical_lineups"
    __table_args__ = (
        UniqueConstraint(
            "mlb_game_pk", "team_mlb_id", "player_mlb_id", name="uq_historical_lineups_game_team_player"
        ),
    )

    historical_lineup_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    mlb_game_pk: Mapped[int] = mapped_column(Integer, nullable=False)
    game_date: Mapped[date] = mapped_column(Date, nullable=False)
    team_mlb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    player_mlb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    batting_order: Mapped[str | None] = mapped_column(String)
    position: Mapped[str | None] = mapped_column(String)
    capture_mode: Mapped[str] = mapped_column(String, nullable=False, default=CAPTURE_MODE_HISTORICAL_ACTUAL)
    source_id: Mapped[str] = mapped_column(String, ForeignKey("sources.source_id"), nullable=False)
    backfill_run_id: Mapped[str | None] = mapped_column(String, ForeignKey("backfill_runs.backfill_run_id"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class HistoricalWeatherObservation(Base):
    """One game's actual observed weather condition/temperature/wind, from
    the SAME MLB live-feed payload `historical/backfill.py`'s
    `process_game_feed` already fetches per game (`gameData.weather`) --
    ground truth for that specific game (what MLB itself recorded at that
    park that day), not a nearby-station archive approximation reconstructed
    after the fact. Dome/retractable-roof venues report MLB's own condition
    value as-is (e.g. "Dome", "Roof Closed") rather than a synthesized
    outdoor reading -- `features/builders.py`'s `compute_weather_adjustment`
    already falls back to neutral on a non-numeric/missing `temp_f`, so no
    special-casing is needed here.

    The original backfill pass (docs/HISTORICAL_BACKFILL_DESIGN.md) only
    kept the pitching/lineup blocks of each feed payload, discarding the
    top-level `gameData.weather` it had already fetched. This table
    captures that same already-fetched field going forward
    (`process_game_feed` now upserts it directly) and backfills it for
    already-processed games via a dedicated `process_weather_for_game`
    pass that re-fetches the same feed URL specifically for this field.
    """

    __tablename__ = "historical_weather_observations"
    __table_args__ = (Index("ix_historical_weather_observations_game_date", "game_date"),)

    historical_weather_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    mlb_game_pk: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    game_date: Mapped[date] = mapped_column(Date, nullable=False)
    venue_mlb_id: Mapped[int | None] = mapped_column(Integer)
    condition: Mapped[str | None] = mapped_column(String)
    temp_f: Mapped[float | None] = mapped_column(Numeric)
    wind_mph: Mapped[float | None] = mapped_column(Numeric)
    wind_detail: Mapped[str | None] = mapped_column(String)
    capture_mode: Mapped[str] = mapped_column(String, nullable=False, default=CAPTURE_MODE_HISTORICAL_ACTUAL)
    source_id: Mapped[str] = mapped_column(String, ForeignKey("sources.source_id"), nullable=False)
    backfill_run_id: Mapped[str | None] = mapped_column(String, ForeignKey("backfill_runs.backfill_run_id"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
