"""add lineup source kind

Revision ID: d31a32076841
Revises: b09cb74d06a7
Create Date: 2026-08-06 16:44:40.289133
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d31a32076841"
down_revision: str | None = "b09cb74d06a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_SOURCE_KINDS = ("schedule", "pitcher_stats", "weather", "park", "umpire", "lines")
NEW_SOURCE_KINDS = (*OLD_SOURCE_KINDS, "lineup")


def upgrade() -> None:
    op.drop_constraint("ck_sources_kind", "sources", type_="check")
    op.create_check_constraint("ck_sources_kind", "sources", f"kind IN {NEW_SOURCE_KINDS}")


def downgrade() -> None:
    op.drop_constraint("ck_sources_kind", "sources", type_="check")
    op.create_check_constraint("ck_sources_kind", "sources", f"kind IN {OLD_SOURCE_KINDS}")
