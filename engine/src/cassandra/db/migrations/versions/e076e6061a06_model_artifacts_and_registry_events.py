"""model artifacts and registry events

Revision ID: e076e6061a06
Revises: d71edca7eb30
Create Date: 2026-08-07 05:28:51.951567
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e076e6061a06"
down_revision: str | None = "d71edca7eb30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Phase 3A/3B (mission directive): durable, append-only model artifacts
# and registry status-change events -- see db/models/registry.py's module
# docstring for the full design rationale (no mutable status column;
# "current status" always derived from the latest event).
NEW_IMMUTABLE_TABLES = ["model_artifacts", "model_registry_events"]

# The trigger function itself already exists (created by
# d764bb3bb5c1_immutable_table_mutation_block_triggers.py) -- reused here,
# not recreated, for these two new tables.
TRIGGER_FUNCTION = "cassandra_block_immutable_mutation"


def upgrade() -> None:
    op.create_table(
        "model_artifacts",
        sa.Column("artifact_id", sa.String(), nullable=False),
        sa.Column("model_family", sa.String(), nullable=False),
        sa.Column("model_code_version", sa.String(), nullable=False),
        sa.Column("fitted_model_version", sa.String(), nullable=False),
        sa.Column("coefficients", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("coefficient_order", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("intercept", sa.Numeric(), nullable=False),
        sa.Column("preprocessing_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("training_dataset_id", sa.String(), nullable=False),
        sa.Column("dataset_builder_version", sa.String(), nullable=False),
        sa.Column("availability_policy_version", sa.String(), nullable=False),
        sa.Column("feature_set_version", sa.String(), nullable=False),
        sa.Column("training_seasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("training_game_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("training_row_count", sa.Integer(), nullable=False),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_git_sha", sa.String(), nullable=True),
        sa.Column("artifact_checksum", sa.String(), nullable=False),
        sa.Column("dependency_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("training_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evaluation_report_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("artifact_id"),
        sa.UniqueConstraint("fitted_model_version"),
    )
    op.create_table(
        "model_registry_events",
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("artifact_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("from_status", sa.String(), nullable=True),
        sa.Column("to_status", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("operator", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("git_commit_sha", sa.String(), nullable=True),
        sa.CheckConstraint(
            "to_status IN "
            "('CANDIDATE', 'SHADOW', 'APPROVED', 'ACTIVE', 'RETIRED', 'REJECTED', 'ROLLED_BACK')",
            name="ck_model_registry_events_to_status",
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["model_artifacts.artifact_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_model_registry_events_artifact_id", "model_registry_events", ["artifact_id"], unique=False
    )

    # Append-only, same full pattern already established for raw_*/
    # projections/grades/audit_events (ADR 0001, CLAUDE.md non-negotiable
    # #3) -- applied here in one migration since the correct final shape
    # is already known (see d764bb3bb5c1/ee1a1af7126d's comments for why
    # a bare REVOKE UPDATE alone breaks on an FK-referenced table like
    # model_artifacts, and why TRUNCATE needs its own separate REVOKE).
    current_user = op.get_bind().engine.url.username
    for table in NEW_IMMUTABLE_TABLES:
        op.execute(f'REVOKE UPDATE, DELETE, TRUNCATE ON "{table}" FROM "{current_user}"')
        op.execute(f'GRANT UPDATE ON "{table}" TO "{current_user}"')
        op.execute(
            f"CREATE TRIGGER block_mutation_{table} "
            f'BEFORE UPDATE OR DELETE ON "{table}" '
            f"FOR EACH ROW EXECUTE FUNCTION {TRIGGER_FUNCTION}()"
        )


def downgrade() -> None:
    current_user = op.get_bind().engine.url.username
    for table in NEW_IMMUTABLE_TABLES:
        op.execute(f'DROP TRIGGER block_mutation_{table} ON "{table}"')
        op.execute(f'GRANT DELETE, TRUNCATE ON "{table}" TO "{current_user}"')

    op.drop_index("ix_model_registry_events_artifact_id", table_name="model_registry_events")
    op.drop_table("model_registry_events")
    op.drop_table("model_artifacts")
