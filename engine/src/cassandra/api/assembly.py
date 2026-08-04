"""Assembles `ProjectionOut` from a `Projection` row plus its cheap
identity joins (player/team names) and optional current grade. Shared by
the today/ledger routers so both surfaces stay consistent.

Per CLAUDE.md's do-not-do list, `raw_final_box_scores` (outcome data) is
never read here. `raw_probable_pitchers` is a narrow, deliberate
exception: it's the only place "which side is this pitcher on" is
recorded, and that's needed to label `team`/`opponent` correctly (not
just "home"/"away") for display. This is a current-best-known-value
lookup for UI labeling, not a point-in-time-bounded decision input, so it
intentionally does not go through pit/asof.py's cutoff filtering -- the
already-published `decision`/`line`/etc. on the projection are never
touched by this lookup.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from cassandra.api.schemas import GradeOut, ProjectionOut, ReasonCodeOut
from cassandra.db.models.grading import Grade
from cassandra.db.models.identity import Game, Player, Team
from cassandra.db.models.projection import Projection
from cassandra.db.models.raw import RawProbablePitcher


def _pitcher_team_mlb_id(session: Session, game: Game, player: Player | None) -> int | None:
    if game.mlb_game_pk is None or player is None or player.mlb_person_id is None:
        return None
    stmt = (
        select(RawProbablePitcher.team_mlb_id)
        .where(
            RawProbablePitcher.mlb_game_pk == game.mlb_game_pk,
            RawProbablePitcher.player_mlb_id == player.mlb_person_id,
        )
        .order_by(RawProbablePitcher.ingested_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalars().first()


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
        pitcher_team_mlb_id = _pitcher_team_mlb_id(session, game, player)
        if pitcher_team_mlb_id is not None and away is not None and away.mlb_team_id == pitcher_team_mlb_id:
            team_name, opponent_name = away.name, (home.name if home else None)
        else:
            team_name, opponent_name = (home.name if home else None), (away.name if away else None)

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
