"""Deterministic coverage report by season and data domain
(docs/HISTORICAL_COVERAGE_REPORT.md, `cassandra audit-historical-coverage`).

Scope note: this reports what's actually implemented in this pass --
games/identity, actual starters, pitcher outcomes, lineups, and
backfill_items failure/skip accounting. It deliberately does NOT report
pitch-level, weather, or park-factor coverage percentages, since those
domains aren't backfilled yet (see CURRENT_STATE_AUDIT.md and
docs/HISTORICAL_BACKFILL_DESIGN.md's "not yet built" section) -- a
coverage report claiming a percentage for data that was never collected
would be worse than not reporting it at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from cassandra.db.models.historical import BackfillItem, HistoricalLineup, HistoricalPitcherStart
from cassandra.db.models.identity import Game


@dataclass
class SeasonCoverage:
    season: int
    games_discovered: int = 0
    games_by_type: dict[str, int] = field(default_factory=dict)
    games_final: int = 0
    games_with_pitcher_data: int = 0
    pitcher_starts_collected: int = 0
    starts_with_strikeout_outcome: int = 0
    starts_with_batters_faced: int = 0
    starts_with_pitch_count: int = 0
    reliever_appearances_collected: int = 0
    games_with_lineup_data: int = 0
    lineup_rows_collected: int = 0


@dataclass
class CoverageReport:
    seasons: list[SeasonCoverage]
    failed_games: list[str]
    skipped_games: list[str]
    duplicate_note: str = (
        "Idempotent upsert by natural key (mlb_game_pk, player_mlb_id) prevents duplicate "
        "historical_pitcher_starts rows structurally -- there is no duplicate-count metric "
        "because a duplicate insert is not possible, not because it wasn't checked."
    )
    not_yet_covered: tuple[str, ...] = (
        "pitch-level / plate-appearance detail (Phase A item 6)",
        "historical weather (Phase A item 7)",
        "park factors calculated from prior completed games (Phase A item 8)",
        "rest/workload derived features (Phase A item 9)",
        "opponent rolling strikeout context (Phase A item 10)",
        "historical market lines (explicitly out of scope for this phase per the mission directive)",
    )


def coverage_report(session: Session, seasons: list[int]) -> CoverageReport:
    season_rows: list[SeasonCoverage] = []
    for season in seasons:
        sc = SeasonCoverage(season=season)

        games = session.execute(select(Game.game_type, Game.status).where(Game.season == season)).all()
        sc.games_discovered = len(games)
        for game_type, status in games:
            key = game_type or "UNKNOWN"
            sc.games_by_type[key] = sc.games_by_type.get(key, 0) + 1
            if status == "Final":
                sc.games_final += 1

        starts = (
            session.execute(
                select(HistoricalPitcherStart).where(
                    HistoricalPitcherStart.game_date >= date(season, 1, 1),
                    HistoricalPitcherStart.game_date <= date(season, 12, 31),
                )
            )
            .scalars()
            .all()
        )
        game_pks_with_data = {s.mlb_game_pk for s in starts}
        sc.games_with_pitcher_data = len(game_pks_with_data)
        starter_rows = [s for s in starts if s.is_starter]
        sc.pitcher_starts_collected = len(starter_rows)
        sc.starts_with_strikeout_outcome = sum(1 for s in starter_rows if s.strikeouts is not None)
        sc.starts_with_batters_faced = sum(1 for s in starter_rows if s.batters_faced is not None)
        sc.starts_with_pitch_count = sum(1 for s in starter_rows if s.pitches_thrown is not None)
        sc.reliever_appearances_collected = len(starts) - len(starter_rows)

        lineup_rows = (
            session.execute(
                select(HistoricalLineup.mlb_game_pk).where(
                    HistoricalLineup.game_date >= date(season, 1, 1),
                    HistoricalLineup.game_date <= date(season, 12, 31),
                )
            )
            .scalars()
            .all()
        )
        sc.lineup_rows_collected = len(lineup_rows)
        sc.games_with_lineup_data = len(set(lineup_rows))

        season_rows.append(sc)

    failed = (
        session.execute(
            select(BackfillItem.work_key).where(
                BackfillItem.domain == "game_feed", BackfillItem.status == "failed"
            )
        )
        .scalars()
        .all()
    )
    skipped = (
        session.execute(
            select(BackfillItem.work_key).where(
                BackfillItem.domain == "game_feed", BackfillItem.status == "skipped"
            )
        )
        .scalars()
        .all()
    )

    return CoverageReport(seasons=season_rows, failed_games=sorted(failed), skipped_games=sorted(skipped))


def format_coverage_report(report: CoverageReport) -> str:
    lines: list[str] = []
    for sc in report.seasons:
        lines.append(f"Season {sc.season}:")
        lines.append(f"  games discovered: {sc.games_discovered} (by type: {sc.games_by_type})")
        lines.append(f"  games Final (per schedule status): {sc.games_final}")
        lines.append(f"  games with pitcher data collected: {sc.games_with_pitcher_data}")
        lines.append(f"  starter appearances collected: {sc.pitcher_starts_collected}")
        if sc.pitcher_starts_collected:
            k_pct = 100 * sc.starts_with_strikeout_outcome / sc.pitcher_starts_collected
            bf_pct = 100 * sc.starts_with_batters_faced / sc.pitcher_starts_collected
            pc_pct = 100 * sc.starts_with_pitch_count / sc.pitcher_starts_collected
            lines.append(f"    with strikeout outcome: {sc.starts_with_strikeout_outcome} ({k_pct:.1f}%)")
            lines.append(f"    with batters faced: {sc.starts_with_batters_faced} ({bf_pct:.1f}%)")
            lines.append(f"    with pitch count: {sc.starts_with_pitch_count} ({pc_pct:.1f}%)")
        lines.append(f"  reliever appearances collected: {sc.reliever_appearances_collected}")
        lines.append(
            f"  games with lineup data: {sc.games_with_lineup_data} ({sc.lineup_rows_collected} rows)"
        )
    lines.append("")
    lines.append(f"Failed games ({len(report.failed_games)}): {', '.join(report.failed_games) or 'none'}")
    skipped_desc = ", ".join(report.skipped_games) or "none"
    lines.append(f"Skipped games, not yet Final ({len(report.skipped_games)}): {skipped_desc}")
    lines.append("")
    lines.append(report.duplicate_note)
    lines.append("")
    lines.append("Not yet covered by this backfill pass (reported honestly, not silently omitted):")
    for item in report.not_yet_covered:
        lines.append(f"  - {item}")
    return "\n".join(lines)


__all__ = ["CoverageReport", "SeasonCoverage", "coverage_report", "format_coverage_report"]
