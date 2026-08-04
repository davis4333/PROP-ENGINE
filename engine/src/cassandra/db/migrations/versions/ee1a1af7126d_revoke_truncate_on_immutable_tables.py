"""revoke truncate on immutable tables

Revision ID: ee1a1af7126d
Revises: d764bb3bb5c1
Create Date: 2026-08-04 21:40:05.182570
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ee1a1af7126d"
down_revision: str | None = "d764bb3bb5c1"
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

# ADR 0001 / CLAUDE.md non-negotiable #3, second correction to
# f4b13ecb5ad7's grant design (the first was d764bb3bb5c1's UPDATE/trigger
# fix).
#
# f4b13ecb5ad7 only REVOKEd UPDATE and DELETE. PostgreSQL grants TRUNCATE
# to a table's owner by default, and the connecting `cassandra` role owns
# every table it created -- so TRUNCATE was silently still allowed the
# entire time, confirmed empirically (`TRUNCATE projections` succeeded
# for the app role pre-migration). TRUNCATE is strictly worse than DELETE
# for this table set: it removes every row in one statement and, unlike
# DELETE, does not fire row-level triggers -- so d764bb3bb5c1's
# BEFORE-DELETE mutation-block trigger cannot catch it. REVOKE is the only
# available defense here, and it's a clean one: TRUNCATE takes an
# ACCESS EXCLUSIVE table-level lock, unrelated to the per-row `FOR KEY
# SHARE` lock that foreign-key inserts need (the thing UPDATE had to be
# restored for), so revoking it doesn't reopen that problem -- confirmed
# empirically before writing this migration.


def upgrade() -> None:
    current_user = op.get_bind().engine.url.username
    for table in IMMUTABLE_TABLES:
        op.execute(f'REVOKE TRUNCATE ON "{table}" FROM "{current_user}"')


def downgrade() -> None:
    current_user = op.get_bind().engine.url.username
    for table in IMMUTABLE_TABLES:
        op.execute(f'GRANT TRUNCATE ON "{table}" TO "{current_user}"')
