"""historical backfill tracking and reconstruction tables

Revision ID: f52bee65c091
Revises: ee1a1af7126d
Create Date: 2026-08-05 13:27:29.142719
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f52bee65c091"
down_revision: str | None = "ee1a1af7126d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Idempotent by design, not auto-generated as-is: a production deploy
    # hit "relation backfill_runs already exists" on a retried `alembic
    # upgrade head`. This migration creates 3 tables, 1 index, and 2
    # columns on an existing table as separate non-atomic DDL statements,
    # so a prior run that got partway through before failing or being
    # killed (a Replit restart mid-migration, an unrelated deploy hiccup)
    # can leave some objects created without alembic_version ever
    # advancing past the previous revision -- the next `upgrade head`
    # then tries to recreate the same objects and crashes. Every
    # operation below checks first via sa.inspect() so a re-run from any
    # partially-applied state converges cleanly instead of crashing.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "backfill_runs" not in existing_tables:
        op.create_table(
            "backfill_runs",
            sa.Column("backfill_run_id", sa.String(), nullable=False),
            sa.Column("requested_start_date", sa.Date(), nullable=False),
            sa.Column("requested_end_date", sa.Date(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("domain", sa.String(), nullable=False),
            sa.Column("season", sa.Integer(), nullable=True),
            sa.Column("current_cursor", sa.String(), nullable=True),
            sa.Column("total_work_items", sa.Integer(), nullable=False),
            sa.Column("completed_work_items", sa.Integer(), nullable=False),
            sa.Column("failed_work_items", sa.Integer(), nullable=False),
            sa.Column("skipped_work_items", sa.Integer(), nullable=False),
            sa.Column("retry_count", sa.Integer(), nullable=False),
            sa.Column(
                "started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
            ),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.String(), nullable=True),
            sa.Column("code_commit_sha", sa.String(), nullable=True),
            sa.Column("adapter_version", sa.String(), nullable=True),
            sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("coverage_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.PrimaryKeyConstraint("backfill_run_id"),
        )

    if "backfill_items" not in existing_tables:
        op.create_table(
            "backfill_items",
            sa.Column("backfill_item_id", sa.UUID(), nullable=False),
            sa.Column("backfill_run_id", sa.String(), nullable=False),
            sa.Column("domain", sa.String(), nullable=False),
            sa.Column("work_key", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("last_error", sa.String(), nullable=True),
            sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
            ),
            sa.ForeignKeyConstraint(
                ["backfill_run_id"],
                ["backfill_runs.backfill_run_id"],
            ),
            sa.PrimaryKeyConstraint("backfill_item_id"),
            sa.UniqueConstraint("domain", "work_key", name="uq_backfill_items_domain_work_key"),
        )

    existing_indexes = (
        {ix["name"] for ix in inspector.get_indexes("backfill_items")}
        if "backfill_items" in inspector.get_table_names()
        else set()
    )
    if "ix_backfill_items_run_status" not in existing_indexes:
        op.create_index(
            "ix_backfill_items_run_status", "backfill_items", ["backfill_run_id", "status"], unique=False
        )

    if "historical_lineups" not in existing_tables:
        op.create_table(
            "historical_lineups",
            sa.Column("historical_lineup_id", sa.UUID(), nullable=False),
            sa.Column("mlb_game_pk", sa.Integer(), nullable=False),
            sa.Column("game_date", sa.Date(), nullable=False),
            sa.Column("team_mlb_id", sa.Integer(), nullable=False),
            sa.Column("player_mlb_id", sa.Integer(), nullable=False),
            sa.Column("batting_order", sa.String(), nullable=True),
            sa.Column("position", sa.String(), nullable=True),
            sa.Column("capture_mode", sa.String(), nullable=False),
            sa.Column("source_id", sa.String(), nullable=False),
            sa.Column("backfill_run_id", sa.String(), nullable=True),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "ingested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
            ),
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.ForeignKeyConstraint(
                ["backfill_run_id"],
                ["backfill_runs.backfill_run_id"],
            ),
            sa.ForeignKeyConstraint(
                ["source_id"],
                ["sources.source_id"],
            ),
            sa.PrimaryKeyConstraint("historical_lineup_id"),
            sa.UniqueConstraint(
                "mlb_game_pk", "team_mlb_id", "player_mlb_id", name="uq_historical_lineups_game_team_player"
            ),
        )

    if "historical_pitcher_starts" not in existing_tables:
        op.create_table(
            "historical_pitcher_starts",
            sa.Column("historical_pitcher_start_id", sa.UUID(), nullable=False),
            sa.Column("mlb_game_pk", sa.Integer(), nullable=False),
            sa.Column("game_date", sa.Date(), nullable=False),
            sa.Column("player_mlb_id", sa.Integer(), nullable=False),
            sa.Column("team_mlb_id", sa.Integer(), nullable=True),
            sa.Column("opponent_mlb_id", sa.Integer(), nullable=True),
            sa.Column("is_starter", sa.Boolean(), nullable=False),
            sa.Column("pregame_starter_confirmation_captured", sa.Boolean(), nullable=False),
            sa.Column("batters_faced", sa.Integer(), nullable=True),
            sa.Column("strikeouts", sa.Integer(), nullable=True),
            sa.Column("pitches_thrown", sa.Integer(), nullable=True),
            sa.Column("strikes", sa.Integer(), nullable=True),
            sa.Column("balls", sa.Integer(), nullable=True),
            sa.Column("hits_allowed", sa.Integer(), nullable=True),
            sa.Column("walks", sa.Integer(), nullable=True),
            sa.Column("hit_batters", sa.Integer(), nullable=True),
            sa.Column("home_runs_allowed", sa.Integer(), nullable=True),
            sa.Column("earned_runs", sa.Integer(), nullable=True),
            sa.Column("runs_allowed", sa.Integer(), nullable=True),
            sa.Column("outs_recorded", sa.Integer(), nullable=True),
            sa.Column("innings_pitched", sa.Numeric(), nullable=True),
            sa.Column("decision", sa.String(), nullable=True),
            sa.Column("game_status", sa.String(), nullable=False),
            sa.Column("capture_mode", sa.String(), nullable=False),
            sa.Column("source_id", sa.String(), nullable=False),
            sa.Column("backfill_run_id", sa.String(), nullable=True),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "ingested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
            ),
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("record_hash", sa.String(), nullable=True),
            sa.ForeignKeyConstraint(
                ["backfill_run_id"],
                ["backfill_runs.backfill_run_id"],
            ),
            sa.ForeignKeyConstraint(
                ["source_id"],
                ["sources.source_id"],
            ),
            sa.PrimaryKeyConstraint("historical_pitcher_start_id"),
            sa.UniqueConstraint(
                "mlb_game_pk", "player_mlb_id", name="uq_historical_pitcher_starts_game_player"
            ),
        )

    existing_indexes = (
        {ix["name"] for ix in inspector.get_indexes("historical_pitcher_starts")}
        if "historical_pitcher_starts" in inspector.get_table_names()
        else set()
    )
    if "ix_historical_pitcher_starts_player_date" not in existing_indexes:
        op.create_index(
            "ix_historical_pitcher_starts_player_date",
            "historical_pitcher_starts",
            ["player_mlb_id", "game_date"],
            unique=False,
        )

    existing_game_columns = {c["name"] for c in inspector.get_columns("games")}
    if "game_type" not in existing_game_columns:
        op.add_column("games", sa.Column("game_type", sa.String(), nullable=True))
    if "season" not in existing_game_columns:
        op.add_column("games", sa.Column("season", sa.Integer(), nullable=True))


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("games", "season")
    op.drop_column("games", "game_type")
    op.drop_index("ix_historical_pitcher_starts_player_date", table_name="historical_pitcher_starts")
    op.drop_table("historical_pitcher_starts")
    op.drop_table("historical_lineups")
    op.drop_index("ix_backfill_items_run_status", table_name="backfill_items")
    op.drop_table("backfill_items")
    op.drop_table("backfill_runs")
    # ### end Alembic commands ###
