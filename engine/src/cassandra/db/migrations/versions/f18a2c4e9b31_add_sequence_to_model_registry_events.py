"""add sequence to model_registry_events

Revision ID: f18a2c4e9b31
Revises: e076e6061a06
Create Date: 2026-08-07 06:15:00.000000

Bug found in Phase 4.2's own tests: `occurred_at` used
`server_default=func.now()`, but Postgres's `now()` is frozen at
TRANSACTION start, not statement start -- two registry events written in
the same transaction (exactly what promote_to_active() does: retire the
old ACTIVE artifact and activate the new one together) get byte-identical
`occurred_at` timestamps, making `ORDER BY occurred_at DESC` non-
deterministic between them. `active_artifact()`/`current_status()` need a
real, gap-tolerant total order that's immune to this -- a Postgres
`BIGSERIAL` column (`nextval()` is evaluated per-statement, never frozen
per-transaction) rather than relying on wall-clock time at all.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f18a2c4e9b31"
down_revision: str | None = "e076e6061a06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE model_registry_events ADD COLUMN sequence BIGSERIAL")
    # A UNIQUE CONSTRAINT, not a separately-named unique index -- matches
    # what db/models/registry.py's `unique=True` column declaration
    # actually autogenerates, so `alembic check` sees no drift.
    op.create_unique_constraint("uq_model_registry_events_sequence", "model_registry_events", ["sequence"])


def downgrade() -> None:
    op.drop_constraint("uq_model_registry_events_sequence", "model_registry_events", type_="unique")
    op.execute("ALTER TABLE model_registry_events DROP COLUMN sequence")
