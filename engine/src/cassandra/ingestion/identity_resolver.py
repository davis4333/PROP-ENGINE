"""Upserts into the small canonical identity tables (venues/teams/players/
games) from raw payloads. These tables are deliberately *not*
append-only/immutable (see db/models/identity.py's docstring) -- a
player's current name/team is fine to update in place, unlike a
point-in-time fact.

This is deliberately simple ID-based resolution (MLB's own IDs via
identity_ids.py), not fuzzy/cross-source entity matching. A lines-manual
entry that can't be matched to a known player/game by MLB ID produces
ENTITY_UNMATCHED (see quality_gate.py) rather than attempting fuzzy name
matching -- see CURRENT_STATE_AUDIT.md for why that's an accepted MVP
scope limit, not an oversight.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from cassandra.db.models.identity import Game, Player, Team, Venue
from cassandra.identity_ids import mlb_game_id, mlb_player_id, mlb_team_id, mlb_venue_id


def upsert_venue(session: Session, mlb_id: int, name: str, city: str | None = None) -> str:
    venue_id = mlb_venue_id(mlb_id)
    stmt = pg_insert(Venue).values(venue_id=venue_id, mlb_venue_id=mlb_id, name=name, city=city)
    stmt = stmt.on_conflict_do_update(index_elements=[Venue.venue_id], set_={"name": name, "city": city})
    session.execute(stmt)
    return venue_id


def upsert_team(session: Session, mlb_id: int, name: str, abbreviation: str | None = None) -> str:
    team_id = mlb_team_id(mlb_id)
    stmt = pg_insert(Team).values(team_id=team_id, mlb_team_id=mlb_id, name=name, abbreviation=abbreviation)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Team.team_id], set_={"name": name, "abbreviation": abbreviation}
    )
    session.execute(stmt)
    return team_id


def upsert_player(
    session: Session,
    mlb_id: int,
    full_name: str,
    bats: str | None = None,
    throws: str | None = None,
) -> str:
    player_id = mlb_player_id(mlb_id)
    stmt = pg_insert(Player).values(
        player_id=player_id, mlb_person_id=mlb_id, full_name=full_name, bats=bats, throws=throws
    )
    stmt = stmt.on_conflict_do_update(index_elements=[Player.player_id], set_={"full_name": full_name})
    session.execute(stmt)
    return player_id


def upsert_game(
    session: Session,
    *,
    mlb_game_pk: int,
    game_date: datetime,
    scheduled_start_utc: datetime,
    home_team_id: str | None,
    away_team_id: str | None,
    venue_id: str | None,
    status: str | None,
    game_type: str | None = None,
    season: int | None = None,
) -> str:
    game_id = mlb_game_id(mlb_game_pk)
    values = {
        "game_id": game_id,
        "mlb_game_pk": mlb_game_pk,
        "game_date": game_date,
        "scheduled_start_utc": scheduled_start_utc,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "venue_id": venue_id,
        "status": status,
        "game_type": game_type,
        "season": season,
    }
    stmt = pg_insert(Game).values(**values)
    update_cols = {k: v for k, v in values.items() if k != "game_id"}
    stmt = stmt.on_conflict_do_update(index_elements=[Game.game_id], set_=update_cols)
    session.execute(stmt)
    return game_id


def resolve_identity_from_schedule_payload(session: Session, game_payload: dict[str, Any]) -> str:
    """From one MLB schedule 'game' dict (a raw_schedule_events payload),
    upsert venue/teams/game identity rows. Returns the resolved game_id.

    Also used by the historical backfill's season-range schedule fetch
    (historical/backfill.py) -- same payload shape, MLB's schedule
    endpoint just returns more of them at once for a date range."""
    venue = game_payload.get("venue") or {}
    venue_id = None
    if venue.get("id"):
        venue_id = upsert_venue(session, venue["id"], venue.get("name", "Unknown Venue"))

    home = game_payload["teams"]["home"]["team"]
    away = game_payload["teams"]["away"]["team"]
    home_team_id = upsert_team(session, home["id"], home.get("name", "Unknown Team"))
    away_team_id = upsert_team(session, away["id"], away.get("name", "Unknown Team"))

    scheduled_start = _parse_dt(game_payload["gameDate"])
    official_date = game_payload.get("officialDate")
    game_date = datetime.fromisoformat(official_date) if official_date else scheduled_start
    status = game_payload.get("status", {}).get("abstractGameState")

    return upsert_game(
        session,
        mlb_game_pk=game_payload["gamePk"],
        game_date=game_date,
        scheduled_start_utc=scheduled_start,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        venue_id=venue_id,
        status=status,
        game_type=game_payload.get("gameType"),
        season=int(game_payload["season"]) if game_payload.get("season") else None,
    )


def resolve_identity_from_probable_pitcher_payload(session: Session, pitcher_payload: dict[str, Any]) -> str:
    """From a probablePitcher payload ({"id":..., "fullName":...}), upsert
    the player identity row. Returns the resolved player_id."""
    return upsert_player(session, pitcher_payload["id"], pitcher_payload.get("fullName", "Unknown Player"))


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
