"""The immutable projection ledger (Appendix B of the handbook), amended
per plan-approval feedback -- see docs/adr/0002, 0006, 0008, 0010.

No `is_current` flag: "current" is always
`SELECT DISTINCT ON (logical_key) * ORDER BY logical_key, version DESC`.
This table is never the target of an UPDATE anywhere in the codebase --
the initial migration REVOKEs UPDATE/DELETE for the app DB role, making
that a database-enforced fact. See CLAUDE.md's do-not-do list.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ARRAY, CheckConstraint, DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cassandra.db.base import Base

DECISIONS = ("OVER", "UNDER", "NO_PLAY")
DECISION_STATUSES = ("QUALIFIED", "UNCERTAIN", "HELD", "REJECTED")
# Mission directive: "DEMO/BACKTEST/PAPER/LIVE record classification for
# the public Ledger" -- CLAUDE.md non-negotiable #8 requires anything
# historical/reconstructed to be labeled BACKTEST/PAPER, never LIVE, but
# the separate historical/ subsystem never writes to this table at all
# (see db/models/historical.py's module docstring) -- BACKTEST/PAPER are
# listed here for completeness and future-proofing (per the directive's
# explicit vocabulary) but are not currently written by any code path.
# In practice only two labels are ever actually written today: LIVE (the
# real pipeline, orchestration/run_slate.py's default) and DEMO
# (scripts/seed_demo_slate.py's fixture-replay demo slate, so a real
# operator running `make seed-demo` against a real database can never
# have its rows silently mistaken for genuine live picks). Whether the
# live pipeline should default to LIVE or PAPER during any beta/paper-
# tracking period is a real product decision for Tyler, not guessed at
# here -- LIVE is the existing, unchanged default behavior.
RECORD_LABELS = ("LIVE", "DEMO", "BACKTEST", "PAPER")


class Projection(Base):
    __tablename__ = "projections"
    __table_args__ = (
        CheckConstraint(f"decision IN {DECISIONS}", name="ck_projections_decision"),
        CheckConstraint(f"decision_status IN {DECISION_STATUSES}", name="ck_projections_decision_status"),
        CheckConstraint(f"record_label IN {RECORD_LABELS}", name="ck_projections_record_label"),
        UniqueConstraint("logical_key", "version", name="uq_projections_logical_key_version"),
    )

    projection_id: Mapped[str] = mapped_column(String, primary_key=True)

    # Versioning (ADR 0002): groups all versions of "the same call" for a
    # player/game/market. "Current" is derived by query, never by mutation.
    logical_key: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    supersedes_projection_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("projections.projection_id")
    )

    run_id: Mapped[str] = mapped_column(String, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    sport: Mapped[str] = mapped_column(String, nullable=False, default="MLB")
    market: Mapped[str] = mapped_column(String, nullable=False, default="pitcher_strikeouts")
    player_id: Mapped[str] = mapped_column(String, ForeignKey("players.player_id"), nullable=False)
    game_id: Mapped[str] = mapped_column(String, ForeignKey("games.game_id"), nullable=False)

    line: Mapped[float | None] = mapped_column(Numeric)
    projection_mean: Mapped[float | None] = mapped_column(Numeric)
    projection_sd: Mapped[float | None] = mapped_column(Numeric)
    probability_over: Mapped[float | None] = mapped_column(Numeric)
    probability_under: Mapped[float | None] = mapped_column(Numeric)

    decision: Mapped[str] = mapped_column(String, nullable=False)
    decision_status: Mapped[str] = mapped_column(String, nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)

    # See RECORD_LABELS above. "LIVE" for the real pipeline; anything else
    # must be excluded from official public performance claims by readers
    # (same enforcement pattern as is_late_publication, ADR 0008) -- never
    # hidden, since the immutability/transparency principle applies to
    # every row regardless of label.
    record_label: Mapped[str] = mapped_column(String, nullable=False, default="LIVE")

    model_version: Mapped[str | None] = mapped_column(String)
    feature_set_version: Mapped[str | None] = mapped_column(String)
    # ADR 0010: independently versioned from model_version -- bumped when
    # decision-gate logic/parameters (e.g. edge threshold) change.
    decision_policy_version: Mapped[str | None] = mapped_column(String)
    source_snapshot_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("snapshots.snapshot_id")
    )

    # ADR 0010: deterministic hash over snapshot + features + model_version +
    # decision_policy_version + gate parameters + git_commit_sha. Lets any
    # published row be independently re-derived and verified later.
    reproducibility_hash: Mapped[str | None] = mapped_column(String)
    git_commit_sha: Mapped[str | None] = mapped_column(String)

    # ADR 0002 / 0008: publication is a distinct concept from
    # qualified/evaluated. is_late_publication marks rows published after
    # the game's official publication cutoff -- excluded from official
    # public performance aggregates but never deleted.
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_late_publication: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
