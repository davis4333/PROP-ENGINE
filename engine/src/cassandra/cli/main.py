"""Operator CLI (typer). Thin wrappers over the same service/orchestration
functions the API and tests use -- no logic lives here, only argument
parsing and printed summaries. Each command opens one db.session_scope()
per invocation: commits on success, rolls back and exits non-zero on any
exception.
"""

from __future__ import annotations

import csv
import gzip
import json as json_module
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import typer
from sqlalchemy import select

from cassandra.config import operating_tz
from cassandra.db.models.historical import BackfillRun
from cassandra.db.session import session_scope
from cassandra.historical.backfill import BackfillConfig, retry_failed_items, run_backfill
from cassandra.historical.coverage import coverage_report, format_coverage_report
from cassandra.historical.dataset_builder import (
    DEFAULT_OUTPUT_DIR,
    build_training_dataset,
    list_datasets,
    load_manifest,
)
from cassandra.orchestration.run_slate import grade_slate_run, ingest_slate, run_slate
from cassandra.pit.snapshot_builder import build_snapshot

app = typer.Typer(help="Cassandra operator CLI -- ingest, snapshot, run-slate, grade.")


def _parse_date(value: str) -> date:
    # typer/click have no native `datetime.date` param type -- take the
    # argument as a plain YYYY-MM-DD string and parse it ourselves.
    return date.fromisoformat(value)


def _parse_cutoff(cutoff: str | None) -> datetime:
    if cutoff is None:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(cutoff)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@app.command()
def ingest(
    slate_date: str = typer.Argument(..., help="Slate date, YYYY-MM-DD."),
    cutoff: str | None = typer.Option(None, help="ISO-8601 as-of cutoff; defaults to now (UTC)."),
    lines_drop_dir: Path | None = typer.Option(None, help="Override the lines-manual drop folder."),
) -> None:
    """Pull fresh data from every source adapter for a slate, without
    freezing a snapshot or publishing anything."""
    cutoff_at = _parse_cutoff(cutoff)
    with session_scope() as session:
        results = ingest_slate(session, _parse_date(slate_date), cutoff_at, lines_drop_dir=lines_drop_dir)
    for r in results:
        status = "ok" if r.is_available else "UNAVAILABLE"
        typer.echo(f"  {r.source_name}: {status}, {r.records_written} records written")
        for w in r.warnings:
            typer.echo(f"    warning: {w}")


@app.command()
def snapshot(
    slate_date: str = typer.Argument(..., help="Slate date, YYYY-MM-DD."),
    cutoff: str | None = typer.Option(None, help="ISO-8601 as-of cutoff; defaults to now (UTC)."),
) -> None:
    """Freeze a point-in-time snapshot from already-ingested raw data
    (does not ingest first -- run `ingest` beforehand if needed)."""
    cutoff_at = _parse_cutoff(cutoff)
    with session_scope() as session:
        snap, entries = build_snapshot(session, _parse_date(slate_date), cutoff_at)
        typer.echo(f"snapshot_id={snap.snapshot_id} status={snap.status}")
        typer.echo(f"  {len(entries)} pitcher-slate entries frozen")
        for e in entries:
            starter = f"player_mlb_id={e.probable.player_mlb_id}" if e.probable else "NO STARTER"
            findings = ", ".join(f.reason_code for f in e.quality_findings) or "none"
            typer.echo(
                f"  game={e.game.game_id} team_mlb_id={e.team_mlb_id} starter={starter} findings=[{findings}]"
            )


@app.command(name="run-slate")
def run_slate_cmd(
    slate_date: str = typer.Argument(..., help="Slate date, YYYY-MM-DD."),
    cutoff: str | None = typer.Option(None, help="ISO-8601 as-of cutoff; defaults to now (UTC)."),
    lines_drop_dir: Path | None = typer.Option(None, help="Override the lines-manual drop folder."),
    edge_threshold: float | None = typer.Option(None, help="Override DECISION_EDGE_THRESHOLD for this run."),
    publish: bool = typer.Option(
        True, help="Set published_at on qualifying rows (still logs every row either way)."
    ),
) -> None:
    """Run the full pipeline for a slate: ingest, freeze, project,
    decide, publish."""
    cutoff_at = _parse_cutoff(cutoff)
    with session_scope() as session:
        result = run_slate(
            session,
            _parse_date(slate_date),
            cutoff_at,
            lines_drop_dir=lines_drop_dir,
            edge_threshold=edge_threshold,
            publish=publish,
        )
    typer.echo(f"run_id={result.run_id}")
    typer.echo(
        f"  entries frozen: {result.entries_frozen} ({result.entries_skipped_no_starter} skipped, no starter)"
    )
    typer.echo(f"  projections published: {len(result.projections_published)}")
    for p in result.projections_published:
        typer.echo(f"    {p.player_id} line={p.line} -> {p.decision} ({p.decision_status})")
    for r in result.ingest_results:
        for w in r.warnings:
            typer.echo(f"  warning [{r.source_name}]: {w}")


@app.command()
def grade(
    slate_date: str = typer.Argument(..., help="Slate date, YYYY-MM-DD."),
) -> None:
    """Ingest current box scores and grade every current published
    projection for a slate whose game is now Final. Safe to re-run."""
    with session_scope() as session:
        result = grade_slate_run(session, _parse_date(slate_date))
    typer.echo(f"run_id={result.run_id}")
    typer.echo(f"  grades written: {len(result.grades)}")
    for g in result.grades:
        typer.echo(f"    {g.projection_id}: {g.result} (actual_strikeouts={g.actual_strikeouts})")


def _today_ny() -> date:
    return datetime.now(UTC).astimezone(operating_tz()).date()


@app.command(name="backfill-mlb")
def backfill_mlb_cmd(
    start_date: str = typer.Option(None, "--start-date", help="YYYY-MM-DD. Defaults to 2023-01-01."),
    end_date: str = typer.Option(
        None, "--end-date", help="YYYY-MM-DD, or omit for the current date in America/New_York."
    ),
    season: int | None = typer.Option(
        None, "--season", help="Shortcut for --start-date {season}-01-01 --end-date {season}-12-31."
    ),
    resume: bool = typer.Option(
        True,
        "--resume/--no-resume",
        help="Continue the latest incomplete run for this exact date range instead of starting a new "
        "BackfillRun row (default: on). Idempotency itself does not depend on this flag -- an "
        "already-succeeded game is skipped either way.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Discover games and report counts only; no per-game feed fetches."
    ),
    concurrency: int = typer.Option(
        1,
        "--concurrency",
        help="Reserved for a future concurrent executor -- sequential-only is what actually runs today "
        "regardless of this value (see historical/backfill.py's module docstring).",
    ),
    request_delay: float = typer.Option(0.25, "--request-delay", help="Seconds to sleep between requests."),
    max_retries: int = typer.Option(5, "--max-retries"),
    game_type: list[str] = typer.Option(
        [], "--game-type", help="Restrict to specific MLB gameType codes. Default: store every type returned."
    ),
    json_summary: bool = typer.Option(False, "--json", help="Print a machine-readable JSON summary."),
) -> None:
    """Backfill schedule/games, actual starters, pitcher outcomes, and
    lineups for a real MLB date range. Resumable and idempotent -- safe
    to interrupt (Ctrl-C, restart, deploy) and rerun with the same
    arguments."""
    start = _parse_date(start_date) if start_date else date(2023, 1, 1)
    end = _parse_date(end_date) if end_date else _today_ny()
    if season is not None:
        start = date(season, 1, 1)
        end = min(date(season, 12, 31), _today_ny())

    config = BackfillConfig(
        start_date=start,
        end_date=end,
        concurrency=concurrency,
        request_delay_seconds=request_delay,
        max_retries=max_retries,
        dry_run=dry_run,
        game_types=tuple(game_type) if game_type else None,
    )

    resume_run_id: str | None = None
    if resume:
        with session_scope() as session:
            existing = (
                session.execute(
                    select(BackfillRun)
                    .where(
                        BackfillRun.requested_start_date == start,
                        BackfillRun.requested_end_date == end,
                        BackfillRun.status.in_(["running", "failed", "paused"]),
                    )
                    .order_by(BackfillRun.started_at.desc())
                )
                .scalars()
                .first()
            )
            resume_run_id = existing.backfill_run_id if existing else None

    with session_scope() as session, httpx.Client(timeout=15.0) as client:
        run = run_backfill(session, client, config, resume_run_id=resume_run_id)

    if json_summary:
        typer.echo(
            json_module.dumps(
                {
                    "backfill_run_id": run.backfill_run_id,
                    "status": run.status,
                    "requested_start_date": run.requested_start_date.isoformat(),
                    "requested_end_date": run.requested_end_date.isoformat(),
                    "total_work_items": run.total_work_items,
                    "completed_work_items": run.completed_work_items,
                    "failed_work_items": run.failed_work_items,
                    "skipped_work_items": run.skipped_work_items,
                }
            )
        )
    else:
        typer.echo(f"backfill_run_id={run.backfill_run_id} status={run.status}")
        typer.echo(f"  requested: {run.requested_start_date} .. {run.requested_end_date}")
        typer.echo(
            f"  total={run.total_work_items} completed={run.completed_work_items} "
            f"failed={run.failed_work_items} skipped={run.skipped_work_items}"
        )
        if run.last_error:
            typer.echo(f"  last_error: {run.last_error}")
        typer.echo(f"  to resume: cassandra backfill-mlb --start-date {start} --end-date {end} --resume")

    if run.failed_work_items:
        raise typer.Exit(code=1)


@app.command(name="backfill-status")
def backfill_status_cmd(
    backfill_run_id: str | None = typer.Option(None, "--run-id"),
    json_summary: bool = typer.Option(False, "--json"),
) -> None:
    """Show the most recent backfill runs (or one specific run)."""
    with session_scope() as session:
        if backfill_run_id:
            run = session.get(BackfillRun, backfill_run_id)
            runs = [run] if run else []
        else:
            runs = list(
                session.execute(select(BackfillRun).order_by(BackfillRun.started_at.desc()).limit(5)).scalars()
            )

    if not runs:
        typer.echo("No backfill runs found.")
        raise typer.Exit(code=1)

    if json_summary:
        typer.echo(
            json_module.dumps(
                [
                    {
                        "backfill_run_id": r.backfill_run_id,
                        "status": r.status,
                        "current_cursor": r.current_cursor,
                        "requested_start_date": r.requested_start_date.isoformat(),
                        "requested_end_date": r.requested_end_date.isoformat(),
                        "total_work_items": r.total_work_items,
                        "completed_work_items": r.completed_work_items,
                        "failed_work_items": r.failed_work_items,
                        "skipped_work_items": r.skipped_work_items,
                        "retry_count": r.retry_count,
                        "started_at": r.started_at.isoformat() if r.started_at else None,
                        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                        "last_success_at": r.last_success_at.isoformat() if r.last_success_at else None,
                        "last_error": r.last_error,
                    }
                    for r in runs
                ]
            )
        )
        return

    for r in runs:
        typer.echo(f"{r.backfill_run_id}  status={r.status}  cursor={r.current_cursor}")
        typer.echo(
            f"  {r.requested_start_date}..{r.requested_end_date}  total={r.total_work_items} "
            f"completed={r.completed_work_items} failed={r.failed_work_items} skipped={r.skipped_work_items} "
            f"retries={r.retry_count}"
        )
        if r.last_error:
            typer.echo(f"  last_error: {r.last_error}")


@app.command(name="retry-backfill-failures")
def retry_backfill_failures_cmd(
    backfill_run_id: str = typer.Option(..., "--run-id", help="The backfill run to attribute retries to."),
) -> None:
    """Re-attempts every currently-failed game_feed work item under the
    given run (does not touch games merely skipped for not being Final
    yet -- those resolve automatically on the next `backfill-mlb` pass)."""
    with session_scope() as session:
        run = session.get(BackfillRun, backfill_run_id)
        if run is None:
            typer.echo(f"No backfill run found with id {backfill_run_id}")
            raise typer.Exit(code=1)
        run_config = run.config or {}
        config = BackfillConfig(
            start_date=run.requested_start_date,
            end_date=run.requested_end_date,
            concurrency=run_config.get("concurrency", 1),
            request_delay_seconds=run_config.get("request_delay_seconds", 0.25),
            max_retries=run_config.get("max_retries", 5),
        )
        with httpx.Client(timeout=15.0) as client:
            run = retry_failed_items(session, client, config, run)

    typer.echo(
        f"backfill_run_id={run.backfill_run_id} status={run.status} "
        f"failed_remaining={run.failed_work_items} retry_count={run.retry_count}"
    )
    if run.failed_work_items:
        raise typer.Exit(code=1)


@app.command(name="audit-historical-coverage")
def audit_historical_coverage_cmd(
    start_date: str = typer.Option("2023-01-01", "--start-date"),
    end_date: str | None = typer.Option(None, "--end-date"),
    json_summary: bool = typer.Option(False, "--json"),
) -> None:
    """Deterministic per-season, per-domain coverage report for the
    historical backfill -- games discovered, starter/outcome/lineup
    collection counts and percentages, failed/skipped games, and an
    explicit list of what this backfill pass does not yet cover."""
    start = _parse_date(start_date)
    end = _parse_date(end_date) if end_date else _today_ny()
    seasons = list(range(start.year, end.year + 1))

    with session_scope() as session:
        report = coverage_report(session, seasons)

    if json_summary:
        typer.echo(
            json_module.dumps(
                {
                    "seasons": [
                        {
                            "season": sc.season,
                            "games_discovered": sc.games_discovered,
                            "games_by_type": sc.games_by_type,
                            "games_final": sc.games_final,
                            "games_with_pitcher_data": sc.games_with_pitcher_data,
                            "pitcher_starts_collected": sc.pitcher_starts_collected,
                            "starts_with_strikeout_outcome": sc.starts_with_strikeout_outcome,
                            "starts_with_batters_faced": sc.starts_with_batters_faced,
                            "starts_with_pitch_count": sc.starts_with_pitch_count,
                            "reliever_appearances_collected": sc.reliever_appearances_collected,
                            "games_with_lineup_data": sc.games_with_lineup_data,
                            "lineup_rows_collected": sc.lineup_rows_collected,
                        }
                        for sc in report.seasons
                    ],
                    "failed_games": report.failed_games,
                    "skipped_games": report.skipped_games,
                    "not_yet_covered": list(report.not_yet_covered),
                }
            )
        )
        return

    typer.echo(format_coverage_report(report))


@app.command(name="build-training-dataset")
def build_training_dataset_cmd(
    seasons: str = typer.Option(..., "--seasons", help="Comma-separated season years, e.g. '2023,2024'."),
    game_types: str = typer.Option("R", "--game-types", help="Comma-separated MLB gameType codes."),
    output_dir: str = typer.Option(str(DEFAULT_OUTPUT_DIR), "--output-dir"),
) -> None:
    """Builds and freezes a STRICT_LIVE_COMPATIBLE training dataset from
    the historical backfill (docs/TRAINING_DATASET_SPEC.md). Writes a
    gzipped JSONL data file plus a JSON manifest under --output-dir; never
    overwrites a prior build (each run gets a new dataset_id)."""
    season_list = [int(s.strip()) for s in seasons.split(",") if s.strip()]
    type_list = tuple(t.strip() for t in game_types.split(",") if t.strip())
    with session_scope() as session:
        manifest = build_training_dataset(
            session, seasons=season_list, output_dir=Path(output_dir), game_types=type_list
        )
    typer.echo(
        f"dataset_id={manifest.dataset_id} tier={manifest.tier} rows={manifest.row_count} "
        f"seasons={manifest.seasons} game_types={manifest.game_types}\n"
        f"data: {manifest.output_path}\n"
        f"excluded feature groups: {', '.join(manifest.excluded_feature_groups)}"
    )


@app.command(name="dataset-status")
def dataset_status_cmd(
    output_dir: str = typer.Option(str(DEFAULT_OUTPUT_DIR), "--output-dir"),
    json_summary: bool = typer.Option(False, "--json"),
) -> None:
    """Lists every training dataset built so far (from its manifest, not
    a DB table -- see dataset_builder.py's module docstring)."""
    manifests = list_datasets(Path(output_dir))
    if json_summary:
        typer.echo(json_module.dumps([asdict(m) for m in manifests], indent=2))
        return
    if not manifests:
        typer.echo(f"No training datasets found under {output_dir}")
        return
    for m in manifests:
        typer.echo(
            f"{m.dataset_id}  built={m.built_at}  tier={m.tier}  rows={m.row_count}  "
            f"seasons={m.seasons}  game_types={m.game_types}"
        )


@app.command(name="audit-training-dataset")
def audit_training_dataset_cmd(
    dataset_id: str = typer.Option(..., "--dataset-id"),
    output_dir: str = typer.Option(str(DEFAULT_OUTPUT_DIR), "--output-dir"),
) -> None:
    """Prints the full manifest for one dataset -- versioning, coverage
    notes, and the explicit list of feature groups it excludes -- so a
    dataset's limitations are checkable before it's used to evaluate or
    train a model."""
    manifest = load_manifest(Path(output_dir), dataset_id)
    typer.echo(json_module.dumps(asdict(manifest), indent=2))


@app.command(name="export-training-dataset")
def export_training_dataset_cmd(
    dataset_id: str = typer.Option(..., "--dataset-id"),
    output_dir: str = typer.Option(str(DEFAULT_OUTPUT_DIR), "--output-dir"),
    export_path: str = typer.Option(..., "--export-path", help="Destination .csv path."),
) -> None:
    """Decompresses one dataset's JSONL rows to a flat CSV for handing to
    non-Python tooling. The frozen .jsonl.gz remains the source of
    truth -- this is a read-only convenience export, never regenerated
    data."""
    data_path = Path(output_dir) / f"{dataset_id}.jsonl.gz"
    if not data_path.exists():
        typer.echo(f"No dataset file found: {data_path}")
        raise typer.Exit(code=1)

    rows: list[dict] = []
    with gzip.open(data_path, "rt", encoding="utf-8") as fh:
        for line in fh:
            rows.append(json_module.loads(line))
    if not rows:
        typer.echo("Dataset has zero rows -- nothing to export.")
        raise typer.Exit(code=1)

    fieldnames = list(rows[0].keys())
    with open(export_path, "w", newline="", encoding="utf-8") as out_fh:
        writer = csv.DictWriter(out_fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    typer.echo(f"Exported {len(rows)} rows to {export_path}")


if __name__ == "__main__":
    app()
