"""Assembles `ProjectionOut` from a `Projection` row plus its cheap
identity joins (player/team names) and optional current grade. Shared by
the today/ledger routers so both surfaces stay consistent -- see
CLAUDE.md's do-not-do list: this only ever reads already-published
`projections`/`grades` rows, never raw_* tables.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from cassandra.api.schemas import GradeOut, ProjectionOut, ReasonCodeOut
from cassandra.db.models.grading import Grade
from cassandra.db.models.identity import Game, Player, Team
from cassandra.db.models.projection import Projection


def assemble_projection_out(session: Session, projection: Projection, grade: Grade | None) -> ProjectionOut:
    player = session.get(Player, projection.player_id)
    game = session.get(Game, projection.game_id)

    team_name: str | None = None
    opponent_name: str | None = None
    scheduled_start_utc = projection.as_of
    if game is not None:
        scheduled_start_utc = game.scheduled_start_utc
        home = session.get(Team, game.home_team_id) if game.home_team_id else None
        away = session.get(Team, game.away_team_id) if game.away_team_id else None
        team_name = home.name if home else None
        opponent_name = away.name if away else None

    return ProjectionOut(
        projection_id=projection.projection_id,
        logical_key=projection.logical_key,
        version=projection.version,
        player_id=projection.player_id,
        player_name=player.full_name if player else projection.player_id,
        team=team_name,
        opponent=opponent_name,
        game_id=projection.game_id,
        scheduled_start_utc=scheduled_start_utc,
        line=float(projection.line) if projection.line is not None else None,
        projection_mean=float(projection.projection_mean) if projection.projection_mean is not None else None,
        projection_sd=float(projection.projection_sd) if projection.projection_sd is not None else None,
        probability_over=float(projection.probability_over)
        if projection.probability_over is not None
        else None,
        probability_under=(
            float(projection.probability_under) if projection.probability_under is not None else None
        ),
        decision=projection.decision,
        decision_status=projection.decision_status,
        reason_codes=[ReasonCodeOut.from_code(c) for c in projection.reason_codes],
        model_version=projection.model_version,
        feature_set_version=projection.feature_set_version,
        decision_policy_version=projection.decision_policy_version,
        reproducibility_hash=projection.reproducibility_hash,
        published_at=projection.published_at,
        is_late_publication=projection.is_late_publication,
        grade=(
            GradeOut(
                result=grade.result, actual_strikeouts=grade.actual_strikeouts, graded_at=grade.graded_at
            )
            if grade is not None
            else None
        ),
    )
