"""add record_label to projections

Revision ID: b09cb74d06a7
Revises: f52bee65c091
Create Date: 2026-08-06 16:12:12.820614
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b09cb74d06a7"
down_revision: str | None = "f52bee65c091"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# See db/models/projection.py's RECORD_LABELS docstring for what each
# value means and which code paths actually write it.
RECORD_LABELS = ("LIVE", "DEMO", "BACKTEST", "PAPER")


def upgrade() -> None:
    # server_default="LIVE" here (not just the ORM-level Python default)
    # is what lets this be a single NOT NULL column addition against a
    # table that already has real rows -- every existing projections row
    # is a genuine live pipeline publish, so backfilling them all as
    # "LIVE" is simply true, not a guess.
    op.add_column(
        "projections",
        sa.Column("record_label", sa.String(), nullable=False, server_default="LIVE"),
    )
    # Same literal condition text as db/models/projection.py's
    # CheckConstraint (f"record_label IN {RECORD_LABELS}") so the two
    # never drift apart.
    op.create_check_constraint(
        "ck_projections_record_label",
        "projections",
        f"record_label IN {RECORD_LABELS}",
    )


def downgrade() -> None:
    op.drop_constraint("ck_projections_record_label", "projections", type_="check")
    op.drop_column("projections", "record_label")
