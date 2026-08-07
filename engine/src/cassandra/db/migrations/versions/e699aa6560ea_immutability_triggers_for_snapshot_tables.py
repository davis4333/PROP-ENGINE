"""immutability triggers for snapshot tables

Revision ID: e699aa6560ea
Revises: f18a2c4e9b31
Create Date: 2026-08-07 13:20:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e699aa6560ea"
down_revision: str | None = "f18a2c4e9b31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# f4b13ecb5ad7 (initial schema) never put these three in IMMUTABLE_TABLES,
# and no later migration added them either -- a real gap found by this
# session's point-in-time audit. ADR 0001 requires a frozen snapshot to be
# immutable (a rerun must create a new Snapshot row, never mutate an
# existing one's referenced rows); nothing in application code currently
# violates that (pit/snapshot_builder.py only ever session.add()s new
# snapshot_raw_refs/snapshot_data_quality rows), but the guarantee rested
# entirely on convention, not a DB-level guard, unlike every other table
# this codebase calls immutable.
#
# snapshots itself is genuinely different from every other "immutable"
# table: pit/snapshot_builder.py legitimately INSERTs a Snapshot row as
# status='building' (needed early to get a snapshot_id for the
# snapshot_raw_refs/snapshot_data_quality rows it writes during
# construction), then UPDATEs that same row's status to 'frozen' once
# construction completes (snapshot_builder.py:239) -- a real, necessary
# in-flight transition, not a mutation attempt. The generic
# cassandra_block_immutable_mutation() trigger (reused as-is below for
# snapshot_raw_refs/snapshot_data_quality, which have no such lifecycle)
# would incorrectly block that legitimate transition, so snapshots gets
# its own trigger function that allows exactly one thing: status
# building -> frozen/failed, with every other column unchanged. Once a
# snapshot is no longer 'building', it is fully immutable -- no further
# UPDATE of any kind, and DELETE is always blocked.
NEW_APPEND_ONLY_TABLES = ["snapshot_raw_refs", "snapshot_data_quality"]
GENERIC_TRIGGER_FUNCTION = "cassandra_block_immutable_mutation"
SNAPSHOT_TRIGGER_FUNCTION = "cassandra_block_snapshot_mutation"


def upgrade() -> None:
    current_user = op.get_bind().engine.url.username

    # Full REVOKE-then-GRANT-UPDATE-back-then-trigger pattern (see
    # d764bb3bb5c1's comment for why a bare REVOKE UPDATE alone breaks on a
    # table with an inbound FK -- snapshot_raw_refs/snapshot_data_quality's
    # own snapshot_id both reference snapshots.snapshot_id, so the same
    # FK-row-lock requirement applies here).
    for table in NEW_APPEND_ONLY_TABLES:
        op.execute(f'REVOKE UPDATE, DELETE, TRUNCATE ON "{table}" FROM "{current_user}"')
        op.execute(f'GRANT UPDATE ON "{table}" TO "{current_user}"')
        op.execute(
            f"CREATE TRIGGER block_mutation_{table} "
            f'BEFORE UPDATE OR DELETE ON "{table}" '
            f"FOR EACH ROW EXECUTE FUNCTION {GENERIC_TRIGGER_FUNCTION}()"
        )

    # snapshots: same REVOKE/GRANT shape (projections.source_snapshot_id
    # also references snapshots.snapshot_id), but its own dedicated
    # trigger function instead of the generic one.
    op.execute('REVOKE UPDATE, DELETE, TRUNCATE ON "snapshots" FROM "%s"' % current_user)
    op.execute('GRANT UPDATE ON "snapshots" TO "%s"' % current_user)
    op.execute(
        f"""
        CREATE FUNCTION {SNAPSHOT_TRIGGER_FUNCTION}() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION
                    'immutable table: snapshots is append-only, DELETE not permitted';
            END IF;
            IF OLD.status <> 'building' THEN
                RAISE EXCEPTION
                    'immutable table: snapshots is append-only once frozen/failed, UPDATE not permitted';
            END IF;
            IF NEW.status NOT IN ('frozen', 'failed') THEN
                RAISE EXCEPTION
                    'snapshots: only a building -> frozen/failed transition is permitted, got building -> %',
                    NEW.status;
            END IF;
            IF NEW.snapshot_id <> OLD.snapshot_id
                OR NEW.slate_date <> OLD.slate_date
                OR NEW.cutoff_at <> OLD.cutoff_at
                OR NEW.created_at <> OLD.created_at
                OR NEW.notes IS DISTINCT FROM OLD.notes
            THEN
                RAISE EXCEPTION
                    'snapshots: only the status column may change during the building -> frozen/failed transition';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER block_mutation_snapshots "
        'BEFORE UPDATE OR DELETE ON "snapshots" '
        f"FOR EACH ROW EXECUTE FUNCTION {SNAPSHOT_TRIGGER_FUNCTION}()"
    )


def downgrade() -> None:
    current_user = op.get_bind().engine.url.username

    op.execute('DROP TRIGGER block_mutation_snapshots ON "snapshots"')
    op.execute(f"DROP FUNCTION {SNAPSHOT_TRIGGER_FUNCTION}()")
    op.execute('GRANT DELETE, TRUNCATE ON "snapshots" TO "%s"' % current_user)

    for table in NEW_APPEND_ONLY_TABLES:
        op.execute(f'DROP TRIGGER block_mutation_{table} ON "{table}"')
        op.execute(f'GRANT DELETE, TRUNCATE ON "{table}" TO "{current_user}"')
