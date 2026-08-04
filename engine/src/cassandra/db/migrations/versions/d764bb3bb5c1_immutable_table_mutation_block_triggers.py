"""immutable table mutation-block triggers

Revision ID: d764bb3bb5c1
Revises: f4b13ecb5ad7
Create Date: 2026-08-04 21:17:18.748014
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d764bb3bb5c1"
down_revision: str | None = "f4b13ecb5ad7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same table list as f4b13ecb5ad7's IMMUTABLE_TABLES.
IMMUTABLE_TABLES = [
    "raw_schedule_events",
    "raw_probable_pitchers",
    "raw_lineups",
    "raw_pitcher_game_logs",
    "raw_weather_observations",
    "raw_park_factors",
    "raw_umpire_assignments",
    "raw_lines",
    "raw_final_box_scores",
    "projections",
    "grades",
    "audit_events",
]

TRIGGER_FUNCTION = "cassandra_block_immutable_mutation"

# ADR 0001 / CLAUDE.md non-negotiable #3, correcting f4b13ecb5ad7's approach.
#
# f4b13ecb5ad7 revoked UPDATE/DELETE from the connecting role and claimed
# that alone made these tables append-only. That claim was only tested
# against a table with no foreign keys pointing at it. It breaks for any
# table that a foreign key *references*: PostgreSQL requires the referenced
# row to be locked with `SELECT ... FOR KEY SHARE` as part of every
# referencing INSERT, and running that lock -- like any `FOR UPDATE`/`FOR
# SHARE` variant -- requires UPDATE privilege on the table being locked, not
# merely SELECT/REFERENCES. Confirmed empirically: with UPDATE revoked,
# `projections.supersedes_projection_id -> projections.projection_id` and
# `grades.projection_id -> projections.projection_id` both fail every
# INSERT with "permission denied for table projections", even though the
# inserting role only ever intended to read/lock, never mutate, the parent
# row.
#
# There is no separate "lock-only" grant in PostgreSQL, so the REVOKE-only
# design is unworkable for any immutable table with an inbound FK
# (currently: projections, raw_final_box_scores). Fix: grant UPDATE back
# (required for the FK row lock to succeed) and instead block real mutation
# with a BEFORE UPDATE/DELETE trigger that unconditionally raises. This is
# strictly enforced by Postgres, not application convention -- identical to
# the REVOKE approach in that regard -- and it still holds for every table
# in IMMUTABLE_TABLES for consistency, including ones with no inbound FK
# today, since any future FK addition would hit the same wall otherwise.
# DELETE stays revoked (no FK path ever needs a delete lock to succeed);
# the DELETE trigger is defense-in-depth in case that ever changes.


def upgrade() -> None:
    current_user = op.get_bind().engine.url.username
    op.execute(
        f"""
        CREATE FUNCTION {TRIGGER_FUNCTION}() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'immutable table: % is append-only, % not permitted',
                TG_TABLE_NAME, TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in IMMUTABLE_TABLES:
        op.execute(f'GRANT UPDATE ON "{table}" TO "{current_user}"')
        op.execute(
            f"CREATE TRIGGER block_mutation_{table} "
            f'BEFORE UPDATE OR DELETE ON "{table}" '
            f"FOR EACH ROW EXECUTE FUNCTION {TRIGGER_FUNCTION}()"
        )


def downgrade() -> None:
    current_user = op.get_bind().engine.url.username
    for table in IMMUTABLE_TABLES:
        op.execute(f'DROP TRIGGER block_mutation_{table} ON "{table}"')
        op.execute(f'REVOKE UPDATE ON "{table}" FROM "{current_user}"')
    op.execute(f"DROP FUNCTION {TRIGGER_FUNCTION}()")
