"""Resumable, idempotent historical MLB backfill (2023-present).

Workflow per docs/HISTORICAL_BACKFILL_DESIGN.md, matching the free MLB
Stats API's own shape:

    schedule (one range call per season)
        -> game IDs
        -> one live-feed call per game (covers both teams' full
           boxscores -- pitching lines AND starting lineups in a single
           request, never a separate call per pitcher/team)
        -> normalize -> upsert into historical_pitcher_starts /
           historical_lineups (db/models/historical.py)

Resumability and idempotency both come from the same mechanism:
BackfillItem rows keyed by (domain, work_key), checked before doing any
work and updated after. A work item already marked "succeeded" is never
redone -- rerunning the same date range after an interruption (process
restart, deploy, rate limit, timeout) just walks the same game-ID list
and skips everything already done, with no risk of duplicate historical
rows (historical_pitcher_starts/historical_lineups upsert by natural key
regardless).

Conservative by design: sequential (config.concurrency exists as a
plumbed-through parameter for a future concurrent executor, but is not
implemented as real concurrency yet -- SQLAlchemy's Session is not
thread-safe, and building that safely is a larger change than this pass
scopes; sequential + a real per-request delay is what actually runs
today), bounded retries with exponential backoff and jitter, and treats
429/5xx as retryable but other 4xx as a permanent per-item failure
rather than retrying something that will never succeed.
"""

from __future__ import annotations

import logging
import random
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from cassandra.adapters.schedule_mlb import MLB_STATS_API_BASE
from cassandra.db.models.historical import (
    CAPTURE_MODE_HISTORICAL_ACTUAL,
    CAPTURE_MODE_HISTORICAL_RECONSTRUCTED,
    BackfillItem,
    BackfillRun,
    HistoricalLineup,
    HistoricalPitcherStart,
)
from cassandra.db.models.identity import Game
from cassandra.db.models.sources import Source
from cassandra.ingestion.identity_resolver import resolve_identity_from_schedule_payload

logger = logging.getLogger(__name__)

LIVE_FEED_BASE = "https://statsapi.mlb.com/api/v1.1"
BACKFILL_SOURCE_NAME = "mlb_stats_api_historical_backfill"
BACKFILL_ADAPTER_VERSION = "0.1.0"

SCHEDULE_DOMAIN = "schedule"
GAME_DOMAIN = "game_feed"

DEFAULT_MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0
DEFAULT_REQUEST_DELAY_SECONDS = 0.25  # conservative pacing -- no key/quota on this API, still don't flood it


@dataclass
class BackfillConfig:
    start_date: date
    end_date: date
    concurrency: int = 1
    request_delay_seconds: float = DEFAULT_REQUEST_DELAY_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    dry_run: bool = False
    game_types: tuple[str, ...] | None = None  # None = store every game type returned

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError(f"start_date {self.start_date} must not be after end_date {self.end_date}")


def enumerate_date_range(start: date, end: date) -> list[date]:
    """Every calendar date from start to end inclusive. Used for input
    validation and coverage-window math; the schedule fetch itself uses
    one range call per season rather than iterating this list day by day
    (see module docstring) -- MLB's own schedule endpoint supports a
    startDate/endDate range in a single call, so iterating a whole
    multi-year range one day at a time would be thousands of avoidable
    calls for no benefit."""
    if start > end:
        raise ValueError(f"start {start} must not be after end {end}")
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def seasons_in_range(start: date, end: date) -> list[int]:
    if start > end:
        raise ValueError(f"start {start} must not be after end {end}")
    return list(range(start.year, end.year + 1))


def _season_window(season: int, start: date, end: date) -> tuple[date, date]:
    return max(date(season, 1, 1), start), min(date(season, 12, 31), end)


def _new_backfill_run_id() -> str:
    return f"backfill_{uuid.uuid4().hex[:12]}"


def _current_commit_sha() -> str | None:
    """Best-effort only -- provenance metadata, never load-bearing for
    correctness, so a missing git binary or a non-repo checkout (e.g. a
    packaged deploy) must not fail the backfill."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=Path(__file__).resolve().parent,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _sleep_with_jitter(base_delay: float) -> None:
    time.sleep(base_delay + random.uniform(0, base_delay * 0.25))  # noqa: S311 -- pacing jitter, not security


def _request_with_retry(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    max_retries: int,
    request_delay: float,
) -> httpx.Response | None:
    """Bounded retry with exponential backoff + jitter. 429/5xx are
    retried; any other 4xx is treated as permanent (retrying a 404
    forever wastes calls for no benefit) and returns None immediately.
    Never raises -- returns None after exhausting retries or hitting a
    permanent error, matching every adapter's "never raise" contract
    elsewhere in this codebase (adapters/base.py) so callers always get
    an explicit, handleable outcome."""
    delay = BASE_BACKOFF_SECONDS
    for attempt in range(1, max_retries + 1):
        try:
            response = client.get(url, params=params, timeout=15.0)
        except httpx.HTTPError as exc:
            logger.warning("backfill: request error (attempt %d/%d) %s: %s", attempt, max_retries, url, exc)
            if attempt == max_retries:
                return None
            _sleep_with_jitter(delay)
            delay = min(delay * 2, MAX_BACKOFF_SECONDS)
            continue

        if response.status_code == 429 or response.status_code >= 500:
            logger.warning(
                "backfill: retryable status %d (attempt %d/%d) %s",
                response.status_code,
                attempt,
                max_retries,
                url,
            )
            if attempt == max_retries:
                return None
            _sleep_with_jitter(delay)
            delay = min(delay * 2, MAX_BACKOFF_SECONDS)
            continue

        if response.status_code >= 400:
            logger.warning("backfill: permanent status %d for %s -- not retrying", response.status_code, url)
            return None

        if request_delay:
            time.sleep(request_delay)
        return response
    return None


def _get_or_create_item(
    session: Session, *, backfill_run_id: str, domain: str, work_key: str
) -> BackfillItem:
    existing = session.execute(
        select(BackfillItem).where(BackfillItem.domain == domain, BackfillItem.work_key == work_key)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    item = BackfillItem(backfill_run_id=backfill_run_id, domain=domain, work_key=work_key, status="pending")
    session.add(item)
    session.flush()
    return item


def _mark_item(
    session: Session, item: BackfillItem, *, status: str, run_id: str, error: str | None = None
) -> None:
    """Finalizes one work item AND commits -- deliberately, not just a
    flush. A multi-year backfill can run for a long time; committing
    after every item (rather than relying on the CLI's single
    session_scope() commit at the very end) is what actually makes
    "resumable after a process restart" true. Without this, an
    interruption partway through would roll back every item completed
    since the run started, defeating the whole point of BackfillItem-
    based resumability."""
    item.status = status
    item.attempts += 1
    item.last_error = error
    item.last_attempted_at = datetime.now(UTC)
    item.backfill_run_id = run_id
    if status == "succeeded":
        item.completed_at = datetime.now(UTC)
    session.commit()


def _ensure_backfill_source(session: Session) -> str:
    stmt = pg_insert(Source).values(
        source_id=BACKFILL_SOURCE_NAME,
        name=BACKFILL_SOURCE_NAME,
        kind="pitcher_stats",
        adapter_version=BACKFILL_ADAPTER_VERSION,
        base_url=MLB_STATS_API_BASE,
        is_active=True,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Source.source_id],
        set_={"adapter_version": BACKFILL_ADAPTER_VERSION, "is_active": True},
    )
    session.execute(stmt)
    return BACKFILL_SOURCE_NAME


def discover_games_for_season(
    session: Session,
    client: httpx.Client,
    *,
    season: int,
    window_start: date,
    window_end: date,
    config: BackfillConfig,
    run: BackfillRun,
) -> list[int]:
    """One schedule range call for this season's slice of the requested
    window, upserting venue/team/game identity rows (with game_type and
    season now populated) for every game returned regardless of type --
    storage is unconditional; filtering to a training cohort happens
    later, never at discovery time, so postseason/spring/exhibition data
    is never silently lost.

    The work item is keyed by the exact (season, window_start, window_end)
    triple, not just the season -- keying on season alone would let an
    earlier narrow-window discovery (e.g. a single-day dry run) silently
    "cover" a later, wider request for the same season, since the
    already-succeeded fast path below would trigger without ever having
    actually fetched the wider range. A repeat of the exact same window is
    still correctly skipped; a new, different window for an
    already-discovered season always triggers a real fetch."""
    work_key = f"{season}:{window_start.isoformat()}:{window_end.isoformat()}"
    item = _get_or_create_item(
        session, backfill_run_id=run.backfill_run_id, domain=SCHEDULE_DOMAIN, work_key=work_key
    )
    if item.status == "succeeded":
        rows = session.execute(
            select(Game.mlb_game_pk).where(Game.season == season, Game.mlb_game_pk.isnot(None))
        ).scalars()
        return sorted(pk for pk in rows if pk is not None)

    response = _request_with_retry(
        client,
        f"{MLB_STATS_API_BASE}/schedule",
        params={
            "sportId": 1,
            "startDate": window_start.isoformat(),
            "endDate": window_end.isoformat(),
            "hydrate": "team,venue",
        },
        max_retries=config.max_retries,
        request_delay=config.request_delay_seconds,
    )
    if response is None:
        _mark_item(
            session,
            item,
            status="failed",
            run_id=run.backfill_run_id,
            error="schedule fetch failed after retries",
        )
        return []

    try:
        payload = response.json()
    except ValueError as exc:
        _mark_item(session, item, status="failed", run_id=run.backfill_run_id, error=f"invalid JSON: {exc}")
        return []

    games = [g for d in payload.get("dates", []) for g in d.get("games", [])]
    game_pks: list[int] = []
    for g in games:
        if config.game_types and g.get("gameType") not in config.game_types:
            continue
        if "gamePk" not in g:
            continue
        resolve_identity_from_schedule_payload(session, g)
        game_pks.append(g["gamePk"])
    session.flush()
    _mark_item(session, item, status="succeeded", run_id=run.backfill_run_id)
    return sorted(set(game_pks))


def _parse_innings_pitched(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _upsert_historical_pitcher_start(
    session: Session,
    *,
    mlb_game_pk: int,
    game_date_val: date,
    player_mlb_id: int,
    team_mlb_id: int | None,
    opponent_mlb_id: int | None,
    is_starter: bool,
    pitching: dict[str, Any],
    person: dict[str, Any],
    game_status: str,
    source_id: str,
    backfill_run_id: str,
    observed_at: datetime,
) -> None:
    values: dict[str, Any] = {
        "mlb_game_pk": mlb_game_pk,
        "game_date": game_date_val,
        "player_mlb_id": player_mlb_id,
        "team_mlb_id": team_mlb_id,
        "opponent_mlb_id": opponent_mlb_id,
        "is_starter": is_starter,
        "pregame_starter_confirmation_captured": False,
        "batters_faced": pitching.get("battersFaced"),
        "strikeouts": pitching.get("strikeOuts"),
        "pitches_thrown": pitching.get("numberOfPitches"),
        "strikes": pitching.get("strikes"),
        "balls": pitching.get("balls"),
        "hits_allowed": pitching.get("hits"),
        "walks": pitching.get("baseOnBalls"),
        "hit_batters": pitching.get("hitBatsmen"),
        "home_runs_allowed": pitching.get("homeRuns"),
        "earned_runs": pitching.get("earnedRuns"),
        "runs_allowed": pitching.get("runs"),
        "outs_recorded": pitching.get("outs"),
        "innings_pitched": _parse_innings_pitched(pitching.get("inningsPitched")),
        "decision": pitching.get("note"),
        "game_status": game_status,
        "capture_mode": CAPTURE_MODE_HISTORICAL_RECONSTRUCTED,
        "source_id": source_id,
        "backfill_run_id": backfill_run_id,
        "observed_at": observed_at,
        "payload": {"person": person, "pitching": pitching},
    }
    stmt = pg_insert(HistoricalPitcherStart).values(**values)
    update_cols = {k: v for k, v in values.items() if k not in ("mlb_game_pk", "player_mlb_id")}
    stmt = stmt.on_conflict_do_update(
        index_elements=["mlb_game_pk", "player_mlb_id"],
        set_=update_cols,
    )
    session.execute(stmt)


def _upsert_historical_lineup(
    session: Session,
    *,
    mlb_game_pk: int,
    game_date_val: date,
    team_mlb_id: int,
    player_mlb_id: int,
    batting_order: str | None,
    position: str | None,
    source_id: str,
    backfill_run_id: str,
    observed_at: datetime,
    player_entry: dict[str, Any],
) -> None:
    values: dict[str, Any] = {
        "mlb_game_pk": mlb_game_pk,
        "game_date": game_date_val,
        "team_mlb_id": team_mlb_id,
        "player_mlb_id": player_mlb_id,
        "batting_order": batting_order,
        "position": position,
        "capture_mode": CAPTURE_MODE_HISTORICAL_ACTUAL,
        "source_id": source_id,
        "backfill_run_id": backfill_run_id,
        "observed_at": observed_at,
        "payload": player_entry,
    }
    stmt = pg_insert(HistoricalLineup).values(**values)
    update_cols = {
        k: v for k, v in values.items() if k not in ("mlb_game_pk", "team_mlb_id", "player_mlb_id")
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=["mlb_game_pk", "team_mlb_id", "player_mlb_id"],
        set_=update_cols,
    )
    session.execute(stmt)


def process_game_feed(
    session: Session,
    client: httpx.Client,
    *,
    game_pk: int,
    source_id: str,
    config: BackfillConfig,
    run: BackfillRun,
) -> str:
    """One game's full backfill unit of work. Returns "succeeded",
    "skipped" (game in the requested range hasn't reached Final yet --
    retryable later, not a permanent failure), or "failed". Idempotent:
    a game already marked "succeeded" in backfill_items is not re-fetched
    at all."""
    work_key = str(game_pk)
    item = _get_or_create_item(
        session, backfill_run_id=run.backfill_run_id, domain=GAME_DOMAIN, work_key=work_key
    )
    if item.status == "succeeded":
        return "succeeded"

    response = _request_with_retry(
        client,
        f"{LIVE_FEED_BASE}/game/{game_pk}/feed/live",
        max_retries=config.max_retries,
        request_delay=config.request_delay_seconds,
    )
    if response is None:
        _mark_item(
            session,
            item,
            status="failed",
            run_id=run.backfill_run_id,
            error="feed fetch failed after retries",
        )
        return "failed"

    try:
        payload = response.json()
    except ValueError as exc:
        _mark_item(session, item, status="failed", run_id=run.backfill_run_id, error=f"invalid JSON: {exc}")
        return "failed"

    game_status = payload.get("gameData", {}).get("status", {}).get("abstractGameState", "Unknown")
    if game_status != "Final":
        _mark_item(
            session,
            item,
            status="skipped",
            run_id=run.backfill_run_id,
            error=f"game_status={game_status}, not yet Final",
        )
        return "skipped"

    official_date = payload.get("gameData", {}).get("datetime", {}).get("officialDate")
    if not official_date:
        _mark_item(session, item, status="failed", run_id=run.backfill_run_id, error="missing officialDate")
        return "failed"
    game_date_val = date.fromisoformat(official_date)

    fetched_at = datetime.now(UTC)
    teams = payload.get("liveData", {}).get("boxscore", {}).get("teams", {})
    team_mlb_ids = {side: (teams.get(side, {}).get("team", {}) or {}).get("id") for side in ("home", "away")}

    pitcher_rows = 0
    for side in ("home", "away"):
        opponent_side = "away" if side == "home" else "home"
        players = teams.get(side, {}).get("players", {})
        for player_entry in players.values():
            pitching = player_entry.get("stats", {}).get("pitching") or {}
            if not pitching:
                continue
            person = player_entry.get("person", {})
            player_mlb_id = person.get("id")
            if player_mlb_id is None:
                continue
            _upsert_historical_pitcher_start(
                session,
                mlb_game_pk=game_pk,
                game_date_val=game_date_val,
                player_mlb_id=player_mlb_id,
                team_mlb_id=team_mlb_ids.get(side),
                opponent_mlb_id=team_mlb_ids.get(opponent_side),
                is_starter=bool(pitching.get("gamesStarted")),
                pitching=pitching,
                person=person,
                game_status=game_status,
                source_id=source_id,
                backfill_run_id=run.backfill_run_id,
                observed_at=fetched_at,
            )
            pitcher_rows += 1

        batting_order = teams.get(side, {}).get("battingOrder") or []
        team_mlb_id = team_mlb_ids.get(side)
        if team_mlb_id is not None:
            for pid in batting_order:
                player_entry = players.get(f"ID{pid}")
                if player_entry is None:
                    continue
                _upsert_historical_lineup(
                    session,
                    mlb_game_pk=game_pk,
                    game_date_val=game_date_val,
                    team_mlb_id=team_mlb_id,
                    player_mlb_id=pid,
                    batting_order=player_entry.get("battingOrder"),
                    position=(player_entry.get("position") or {}).get("abbreviation"),
                    source_id=source_id,
                    backfill_run_id=run.backfill_run_id,
                    observed_at=fetched_at,
                    player_entry=player_entry,
                )

    session.flush()
    if pitcher_rows == 0:
        _mark_item(
            session,
            item,
            status="failed",
            run_id=run.backfill_run_id,
            error="Final game with no pitching lines found in boxscore",
        )
        return "failed"

    _mark_item(session, item, status="succeeded", run_id=run.backfill_run_id)
    return "succeeded"


def run_backfill(
    session: Session,
    client: httpx.Client,
    config: BackfillConfig,
    *,
    resume_run_id: str | None = None,
) -> BackfillRun:
    """The top-level entry point cli/main.py's `backfill-mlb` calls.
    Safe to call repeatedly for the same (or overlapping) date range --
    already-succeeded work items are skipped, never redone or
    duplicated."""
    if resume_run_id:
        run = session.get(BackfillRun, resume_run_id)
        if run is None:
            raise ValueError(f"No backfill run found with id {resume_run_id!r}")
        run.status = "running"
        session.commit()
    else:
        run = BackfillRun(
            backfill_run_id=_new_backfill_run_id(),
            requested_start_date=config.start_date,
            requested_end_date=config.end_date,
            status="running",
            source=BACKFILL_SOURCE_NAME,
            domain="mlb_core",
            config={
                "concurrency": config.concurrency,
                "request_delay_seconds": config.request_delay_seconds,
                "max_retries": config.max_retries,
                "game_types": list(config.game_types) if config.game_types else None,
                "dry_run": config.dry_run,
            },
            code_commit_sha=_current_commit_sha(),
            adapter_version=BACKFILL_ADAPTER_VERSION,
        )
        session.add(run)
        session.commit()

    source_id = _ensure_backfill_source(session)
    session.commit()

    all_game_pks: list[int] = []
    for season in seasons_in_range(config.start_date, config.end_date):
        run.current_cursor = f"season:{season}:schedule"
        session.commit()
        window_start, window_end = _season_window(season, config.start_date, config.end_date)
        game_pks = discover_games_for_season(
            session,
            client,
            season=season,
            window_start=window_start,
            window_end=window_end,
            config=config,
            run=run,
        )
        all_game_pks.extend(game_pks)

    all_game_pks = sorted(set(all_game_pks))
    run.total_work_items = len(all_game_pks)
    session.commit()

    if config.dry_run:
        run.status = "completed"
        run.finished_at = datetime.now(UTC)
        run.coverage_summary = {"dry_run": True, "games_discovered": len(all_game_pks)}
        session.commit()
        return run

    for game_pk in all_game_pks:
        run.current_cursor = f"game:{game_pk}"
        outcome = process_game_feed(
            session, client, game_pk=game_pk, source_id=source_id, config=config, run=run
        )
        if outcome == "succeeded":
            run.completed_work_items += 1
            run.last_success_at = datetime.now(UTC)
        elif outcome == "skipped":
            run.skipped_work_items += 1
        else:
            run.failed_work_items += 1
            run.last_error = f"game {game_pk}: see backfill_items.last_error"
        session.commit()

    run.status = "completed"
    run.finished_at = datetime.now(UTC)
    session.commit()
    return run


def retry_failed_items(
    session: Session, client: httpx.Client, config: BackfillConfig, run: BackfillRun
) -> BackfillRun:
    """Re-attempts every backfill_items row currently marked "failed" for
    the game_feed domain, under the given run. Does not touch "skipped"
    items (a game not yet Final isn't a failure to retry on demand --
    it's picked up automatically the next time a full backfill-mlb pass
    walks the same date range, once the game has actually finished)."""
    run.status = "running"
    session.commit()
    failed = (
        session.execute(
            select(BackfillItem).where(BackfillItem.domain == GAME_DOMAIN, BackfillItem.status == "failed")
        )
        .scalars()
        .all()
    )
    source_id = _ensure_backfill_source(session)
    for item in failed:
        item.status = "pending"
    session.commit()

    for item in failed:
        game_pk = int(item.work_key)
        run.current_cursor = f"retry:game:{game_pk}"
        outcome = process_game_feed(
            session, client, game_pk=game_pk, source_id=source_id, config=config, run=run
        )
        if outcome == "succeeded":
            run.completed_work_items += 1
            run.failed_work_items = max(0, run.failed_work_items - 1)
            run.last_success_at = datetime.now(UTC)
        elif outcome == "failed":
            run.last_error = f"retry of game {game_pk} failed again"
        session.commit()

    run.retry_count += 1
    run.status = "completed"
    run.finished_at = datetime.now(UTC)
    session.commit()
    return run
