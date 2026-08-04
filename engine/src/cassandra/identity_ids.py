"""Deterministic string-ID scheme for MLB-sourced entities.

Used consistently by every adapter that needs to reference an identity
entity (venues/teams/players/games) as a string, and by
`ingestion/identity_resolver.py` when upserting those entities -- so a
`raw_park_factors.venue_id` value and a `venues.venue_id` primary key
always agree without needing a live join back through `mlb_venue_id`.
"""

from __future__ import annotations


def mlb_venue_id(mlb_id: int) -> str:
    return f"mlb_venue_{mlb_id}"


def mlb_team_id(mlb_id: int) -> str:
    return f"mlb_team_{mlb_id}"


def mlb_player_id(mlb_id: int) -> str:
    return f"mlb_player_{mlb_id}"


def mlb_game_id(mlb_game_pk: int) -> str:
    return f"mlb_game_{mlb_game_pk}"
