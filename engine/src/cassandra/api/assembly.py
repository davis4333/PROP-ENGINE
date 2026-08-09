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

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from cassandra.api.schemas import GradeOut, ProjectionOut, ReasonCodeOut
from cassandra.db.models.features import FeatureValue
from cassandra.db.models.grading import Grade
from cassandra.db.models.identity import Game, Player, Team
from cassandra.db.models.projection import Projection
from cassandra.db.models.raw import RawLine, RawProbablePitcher
from cassandra.decision.engine import edge_for_display
from cassandra.decision.explain import build_explanation
from cassandra.pit.asof import all_as_of


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


def _features_for(session: Session, projection: Projection) -> dict[str, object] | None:
    """The exact features blob build_features() computed for this
    projection -- joined by (snapshot_id, player_id, game_id,
    feature_set_version), the same keys features/builders.py's caller
    (orchestration/run_slate.py) wrote it under. None only if a
    projection somehow lacks a snapshot/feature_set_version (shouldn't
    happen for a real pipeline row) or the row genuinely isn't there."""
    if projection.source_snapshot_id is None or projection.feature_set_version is None:
        return None
    stmt = (
        select(FeatureValue.features)
        .where(
            FeatureValue.snapshot_id == projection.source_snapshot_id,
            FeatureValue.player_id == projection.player_id,
            FeatureValue.game_id == projection.game_id,
            FeatureValue.feature_set_version == projection.feature_set_version,
        )
        .limit(1)
    )
    return session.execute(stmt).scalars().first()


def _line_provenance_for(
    session: Session, projection: Projection, game: Game | None, player: Player | None
) -> tuple[str | None, datetime | None]:
    """Re-derives which raw_lines source/observation the decision was
    actually made against, via the exact same point-in-time as-of query
    pit/snapshot_builder.py used at publish time (cutoff=projection.as_of,
    which is permanently fixed once published) -- never a fresh "latest
    line right now" lookup, which could show a source/age that has
    nothing to do with what was actually decided. (source, observed_at),
    both None when there's no line (or identity can't be resolved)."""
    if game is None or game.mlb_game_pk is None or player is None or player.mlb_person_id is None:
        return None, None
    lines = all_as_of(
        session,
        RawLine,
        {
            "mlb_game_pk": game.mlb_game_pk,
            "player_mlb_id": player.mlb_person_id,
            "market": projection.market,
        },
        projection.as_of,
    )
    if not lines:
        return None, None
    latest = lines[0]
    return latest.source_id, latest.observed_at


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

    projection_mean = float(projection.projection_mean) if projection.projection_mean is not None else None
    line = float(projection.line) if projection.line is not None else None
    probability_over = float(projection.probability_over) if projection.probability_over is not None else None
    probability_under = (
        float(projection.probability_under) if projection.probability_under is not None else None
    )
    edge = edge_for_display(probability_over, probability_under)
    features = _features_for(session, projection)
    line_source, line_observed_at = _line_provenance_for(session, projection, game, player)
    why, risks = build_explanation(
        decision=projection.decision,
        decision_status=projection.decision_status,
        projection_mean=projection_mean,
        line=line,
        edge=edge,
        features=features,
        reason_codes=list(projection.reason_codes),
    )

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
        line=line,
        projection_mean=projection_mean,
        projection_sd=float(projection.projection_sd) if projection.projection_sd is not None else None,
        probability_over=probability_over,
        probability_under=probability_under,
        probability_push=(
            float(projection.probability_push) if projection.probability_push is not None else None
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
        record_label=projection.record_label,
        edge=edge,
        line_source=line_source,
        line_observed_at=line_observed_at,
        why=why,
        risks=risks,
        grade=(
            GradeOut(
                result=grade.result, actual_strikeouts=grade.actual_strikeouts, graded_at=grade.graded_at
            )
            if grade is not None
            else None
        ),
    )
