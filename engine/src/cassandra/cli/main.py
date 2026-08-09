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
from typing import Any

import httpx
import typer
from sqlalchemy import select

from cassandra.config import operating_tz
from cassandra.db.models.historical import BackfillRun
from cassandra.db.models.registry import ModelArtifact, ModelRegistryEvent
from cassandra.db.session import session_scope
from cassandra.historical.backfill import (
    BackfillConfig,
    retry_failed_items,
    run_backfill,
    run_weather_backfill,
)
from cassandra.historical.coverage import coverage_report, format_coverage_report
from cassandra.historical.dataset_builder import (
    DEFAULT_OUTPUT_DIR,
    build_training_dataset,
    list_datasets,
    load_manifest,
)
from cassandra.historical.evaluation import evaluate_model, write_evaluation_report
from cassandra.models.baseline import BaselinePoissonModel
from cassandra.orchestration.run_slate import grade_slate_run, ingest_slate, run_slate
from cassandra.pit.snapshot_builder import build_snapshot
from cassandra.registry.service import (
    promote_to_active,
    resolve_active_model,
    rollback_active,
)

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
                session.execute(
                    select(BackfillRun).order_by(BackfillRun.started_at.desc()).limit(5)
                ).scalars()
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


@app.command(name="backfill-weather")
def backfill_weather_cmd(
    start_date: str = typer.Option(None, "--start-date", help="YYYY-MM-DD. Defaults to 2023-01-01."),
    end_date: str = typer.Option(
        None, "--end-date", help="YYYY-MM-DD, or omit for the current date in America/New_York."
    ),
    resume: bool = typer.Option(
        True,
        "--resume/--no-resume",
        help="Continue the latest incomplete weather-backfill run for this exact date range instead of "
        "starting a new BackfillRun row.",
    ),
    request_delay: float = typer.Option(0.25, "--request-delay", help="Seconds to sleep between requests."),
    max_retries: int = typer.Option(5, "--max-retries"),
    json_summary: bool = typer.Option(False, "--json", help="Print a machine-readable JSON summary."),
) -> None:
    """Enrich already-backfilled games (from `backfill-mlb`) with weather --
    a separate pass (docs/HISTORICAL_BACKFILL_DESIGN.md's weather item),
    since the original backfill's game-feed fetches didn't retain
    `gameData.weather`. A NEW game backfilled after this feature shipped
    picks up weather automatically on its first `backfill-mlb` pass; this
    command is for enriching games backfilled before that. Resumable and
    idempotent, same as `backfill-mlb`."""
    start = _parse_date(start_date) if start_date else date(2023, 1, 1)
    end = _parse_date(end_date) if end_date else _today_ny()

    config = BackfillConfig(
        start_date=start, end_date=end, request_delay_seconds=request_delay, max_retries=max_retries
    )

    resume_run_id: str | None = None
    if resume:
        with session_scope() as session:
            existing = (
                session.execute(
                    select(BackfillRun)
                    .where(
                        BackfillRun.domain == "weather",
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
        run = run_weather_backfill(session, client, config, resume_run_id=resume_run_id)

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
        typer.echo(
            f"  total={run.total_work_items} completed={run.completed_work_items} "
            f"failed={run.failed_work_items} skipped={run.skipped_work_items}"
        )
        if run.last_error:
            typer.echo(f"  last_error: {run.last_error}")
        typer.echo(f"  to resume: cassandra backfill-weather --start-date {start} --end-date {end} --resume")

    if run.failed_work_items:
        raise typer.Exit(code=1)


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


@app.command(name="evaluate-baseline")
def evaluate_baseline_cmd(
    dataset_id: str = typer.Option(..., "--dataset-id"),
    output_dir: str = typer.Option(str(DEFAULT_OUTPUT_DIR), "--output-dir"),
) -> None:
    """Evaluates the permanent baseline model (`k-model-0.1.0`, unchanged)
    against a frozen training dataset -- MAE/RMSE/bias/Poisson deviance
    and threshold calibration (historical/evaluation.py). Writes a
    HISTORICAL_RECONSTRUCTION-labeled report file; never writes to the
    live `projections`/`grades` tables (CLAUDE.md non-negotiable #8)."""
    data_path = Path(output_dir) / f"{dataset_id}.jsonl.gz"
    if not data_path.exists():
        typer.echo(f"No dataset file found: {data_path}")
        raise typer.Exit(code=1)

    rows: list[dict] = []
    with gzip.open(data_path, "rt", encoding="utf-8") as fh:
        for line in fh:
            rows.append(json_module.loads(line))

    report = evaluate_model(rows, BaselinePoissonModel(), dataset_id=dataset_id)
    report_path = write_evaluation_report(report, Path(output_dir) / "evaluations")

    typer.echo(
        f"evaluation_id={report.evaluation_id} label={report.record_label} "
        f"model_version={report.model_version} dataset_id={dataset_id}\n"
        f"n_rows={report.n_rows} skipped={report.n_rows_skipped_missing_label}\n"
        f"mae={report.mae:.4f} rmse={report.rmse:.4f} mean_bias={report.mean_bias:.4f} "
        f"mean_poisson_deviance={report.mean_poisson_deviance:.4f}"
    )
    for c in report.calibration:
        typer.echo(
            f"  line={c.threshold}  n={c.n}  predicted_p_over={c.mean_predicted_prob_over:.3f}  "
            f"empirical_over_rate={c.empirical_over_rate:.3f}  brier={c.brier_score:.4f}"
        )
    for tier, stats in report.breakdown_by_recent_k_rate_tier.items():
        typer.echo(f"  tier={tier}  n={stats['n']:.0f}  mae={stats['mae']:.4f}")
    typer.echo(f"report written: {report_path}")


@app.command(name="train-walk-forward-challenger")
def train_walk_forward_challenger_cmd(
    dataset_id: str = typer.Option(..., "--dataset-id"),
    output_dir: str = typer.Option(str(DEFAULT_OUTPUT_DIR), "--output-dir"),
    n_folds: int = typer.Option(5, "--n-folds"),
    family: str = typer.Option(
        "poisson-regression",
        "--family",
        help="Model family, e.g. 'poisson-regression' or 'negative-binomial-regression'.",
    ),
) -> None:
    """Trains a challenger model under time-ordered walk-forward
    validation against a frozen dataset, comparing it fold by fold to the
    permanent, unmodified baseline (`k-model-0.1.0`) AND, whenever a
    model is currently ACTIVE, to that exact model too -- the real
    question a promotion decision needs answered isn't just "does this
    beat the naive baseline" but "is this actually better than what
    Cassandra is using right now" -- historical/walk_forward.py.
    Requires the `training` extra (numpy); imported lazily here so every
    other CLI command keeps working unmodified in an environment that
    hasn't installed it. **No automatic promotion**: this only ever
    writes a frozen, HISTORICAL_RECONSTRUCTION-labeled comparison report
    -- promoting a challenger to production requires a human, per the
    mission directive."""
    try:
        from cassandra.historical.walk_forward import result_to_dict, run_walk_forward_validation
    except ImportError as exc:
        typer.echo(
            "train-walk-forward-challenger needs the 'training' extra "
            f"(numpy). Install with: pip install -e '.[training]'  ({exc})"
        )
        raise typer.Exit(code=1) from exc

    data_path = Path(output_dir) / f"{dataset_id}.jsonl.gz"
    if not data_path.exists():
        typer.echo(f"No dataset file found: {data_path}")
        raise typer.Exit(code=1)

    rows: list[dict] = []
    with gzip.open(data_path, "rt", encoding="utf-8") as fh:
        for line in fh:
            rows.append(json_module.loads(line))

    with session_scope() as session:
        resolved_active = resolve_active_model(session)
    # None whenever nothing has ever been promoted (the permanent
    # baseline is "active" in the sense of what's currently serving, but
    # that's already the unconditional baseline comparison above -- no
    # point comparing the baseline to itself).
    active_model = resolved_active.model if resolved_active.active_artifact_id is not None else None
    active_model_version = resolved_active.model_version if active_model is not None else None

    result = run_walk_forward_validation(
        rows,
        dataset_id=dataset_id,
        n_folds=n_folds,
        family=family,
        active_model=active_model,
        active_model_version=active_model_version,
    )

    eval_dir = Path(output_dir) / "evaluations"
    eval_dir.mkdir(parents=True, exist_ok=True)
    report_path = eval_dir / f"walk_forward_{dataset_id}_{result.challenger_model_version}.json"
    report_path.write_text(json_module.dumps(result_to_dict(result), indent=2))

    active_line = (
        f"active_model={result.active_model_version}  aggregate_active_mae={result.aggregate_active_mae:.4f}"
        if result.aggregate_active_mae is not None
        else "active_model=none (nothing has ever been promoted -- baseline is what's currently serving)"
    )
    typer.echo(
        f"challenger={result.challenger_model_version}  dataset_id={dataset_id}\n"
        f"folds_run={result.n_folds}  folds_skipped_insufficient_data="
        f"{result.n_folds_skipped_insufficient_train_data}\n"
        f"aggregate_baseline_mae={result.aggregate_baseline_mae:.4f}  "
        f"aggregate_challenger_mae={result.aggregate_challenger_mae:.4f}\n"
        f"{active_line}"
    )
    for fold in result.folds:
        active_mae = f"  active_mae={fold.active_report.mae:.4f}" if fold.active_report is not None else ""
        typer.echo(
            f"  fold={fold.fold_index}  train_n={fold.train_n}  val_n={fold.validation_n}  "
            f"val_window={fold.validation_start_date}..{fold.validation_end_date}  "
            f"baseline_mae={fold.baseline_report.mae:.4f}  challenger_mae={fold.challenger_report.mae:.4f}"
            f"{active_mae}"
        )
    typer.echo(
        "out-of-sample tier breakdown (held-out validation rows only -- never a fold's own training rows):"
    )
    tiers = sorted(
        set(result.aggregate_baseline_tier_breakdown) | set(result.aggregate_challenger_tier_breakdown)
    )
    for tier in tiers:
        b = result.aggregate_baseline_tier_breakdown.get(tier, {"n": 0, "mae": 0.0})
        c = result.aggregate_challenger_tier_breakdown.get(tier, {"n": 0, "mae": 0.0})
        typer.echo(
            f"  tier={tier}  n={b['n']:.0f}  baseline_mae={b['mae']:.4f}  challenger_mae={c['mae']:.4f}"
        )
    typer.echo("No automatic promotion -- this is a comparison report only.")
    typer.echo(f"report written: {report_path}")


@app.command(name="train-final-model")
def train_final_model_cmd(
    dataset_id: str = typer.Option(..., "--dataset-id"),
    family: str = typer.Option(..., "--family", help="Model family, e.g. 'poisson-regression'."),
    operator: str = typer.Option(
        ..., "--operator", help="Your identity, recorded on the artifact/registry event."
    ),
    output_dir: str = typer.Option(str(DEFAULT_OUTPUT_DIR), "--output-dir"),
    register: bool = typer.Option(
        False, "--register", help="Register the fitted artifact as CANDIDATE. Never auto-promotes further."
    ),
    notes: str | None = typer.Option(None, "--notes", help="Free-text note stored on the artifact."),
    after_walk_forward_report: str | None = typer.Option(
        None,
        "--after-walk-forward-report",
        help=(
            "Path to a JSON report written by train-walk-forward-challenger. Attaches its "
            "aggregate_baseline_mae/aggregate_challenger_mae/n_folds to this artifact's "
            "training_metrics -- promote-model refuses to promote an artifact that never had "
            "a real out-of-sample comparison attached this way."
        ),
    ),
) -> None:
    """Loads a frozen dataset, fits a FINAL challenger on every eligible
    row (no walk-forward holdout -- see train-walk-forward-challenger for
    that comparison), creates a durable model artifact
    (registry/service.py, db/models/registry.py), proves the artifact
    reloads byte-identically from the database and re-evaluates
    identically once reloaded, and -- only with `--register` -- registers
    it as CANDIDATE. **No automatic promotion**: CANDIDATE is the only
    status this command can ever reach; promoting past it requires a
    separate, explicit, human action (mission directive Phase 3) --
    and, per registry/service.py's promote_to_active(), also requires
    --after-walk-forward-report to have been passed here first."""
    try:
        from cassandra.historical.train_final_model import (
            SUPPORTED_MODEL_FAMILIES,
            train_final_negative_binomial_model,
            train_final_poisson_model,
        )
    except ImportError as exc:
        typer.echo(
            "train-final-model needs the 'training' extra (numpy). "
            f"Install with: pip install -e '.[training]'  ({exc})"
        )
        raise typer.Exit(code=1) from exc

    if family not in SUPPORTED_MODEL_FAMILIES:
        typer.echo(f"Unsupported --family {family!r}. Supported: {', '.join(SUPPORTED_MODEL_FAMILIES)}")
        raise typer.Exit(code=1)

    manifest = load_manifest(Path(output_dir), dataset_id)
    data_path = Path(output_dir) / f"{dataset_id}.jsonl.gz"
    if not data_path.exists():
        typer.echo(f"No dataset file found: {data_path}")
        raise typer.Exit(code=1)

    rows: list[dict] = []
    with gzip.open(data_path, "rt", encoding="utf-8") as fh:
        for line in fh:
            rows.append(json_module.loads(line))

    walk_forward_metrics: dict[str, Any] | None = None
    if after_walk_forward_report:
        wf_path = Path(after_walk_forward_report)
        if not wf_path.exists():
            typer.echo(f"No walk-forward report found: {wf_path}")
            raise typer.Exit(code=1)
        wf_data = json_module.loads(wf_path.read_text())
        walk_forward_metrics = {
            "walk_forward_aggregate_baseline_mae": wf_data["aggregate_baseline_mae"],
            "walk_forward_aggregate_challenger_mae": wf_data["aggregate_challenger_mae"],
            "walk_forward_n_folds": wf_data["n_folds"],
            "walk_forward_dataset_id": wf_data["dataset_id"],
        }

    train_fn = (
        train_final_negative_binomial_model
        if family == "negative-binomial-regression"
        else train_final_poisson_model
    )
    result = train_fn(
        manifest=manifest,
        rows=rows,
        operator=operator,
        output_dir=Path(output_dir),
        register=register,
        notes=notes,
        walk_forward_metrics=walk_forward_metrics,
    )

    typer.echo(
        f"artifact_id={result.artifact_id}\n"
        f"fitted_model_version={result.fitted_model_version}\n"
        f"evaluation_id={result.evaluation_id}\n"
        f"training_row_count={len(rows)}\n"
        f"mae={result.training_metrics['mae']:.4f}  rmse={result.training_metrics['rmse']:.4f}  "
        f"mean_bias={result.training_metrics['mean_bias']:.4f}"
    )
    if result.registered:
        typer.echo(f"registered as CANDIDATE (registry_event_id={result.registry_event_id})")
    else:
        typer.echo("not registered (pass --register to register as CANDIDATE) -- artifact created only.")
    typer.echo("No automatic promotion -- CANDIDATE is the only status this command can reach.")


@app.command(name="promote-model")
def promote_model_cmd(
    artifact_id: str = typer.Option(..., "--artifact-id"),
    operator: str = typer.Option(..., "--operator", help="Your identity, recorded on the registry event."),
    reason: str | None = typer.Option(None, "--reason"),
) -> None:
    """Promotes a registered CANDIDATE artifact to ACTIVE -- the live
    pipeline (orchestration/run_slate.py's PROJECT stage) will use it for
    every run_slate() call from this point on, via
    registry/service.py's resolve_active_model(). Atomically retires
    whatever was previously ACTIVE in the same call. This is the one and
    only way any artifact ever reaches ACTIVE -- there is no automatic
    promotion anywhere in this codebase; running this command with a
    real --operator identity IS the human approval the mission directive
    requires."""
    with session_scope() as session:
        artifact = session.get(ModelArtifact, artifact_id)
        if artifact is None:
            typer.echo(f"No artifact found with artifact_id={artifact_id}")
            raise typer.Exit(code=1)
        typer.echo(
            f"Promoting artifact_id={artifact_id} (model_family={artifact.model_family}, "
            f"trained_at={artifact.trained_at}, training_metrics={artifact.training_metrics}) to ACTIVE..."
        )
        try:
            event = promote_to_active(session, artifact_id=artifact_id, operator=operator, reason=reason)
        except ValueError as exc:
            typer.echo(f"Cannot promote: {exc}")
            raise typer.Exit(code=1) from exc
    typer.echo(f"Promoted. registry_event_id={event.event_id}")


@app.command(name="rollback-model")
def rollback_model_cmd(
    operator: str = typer.Option(..., "--operator", help="Your identity, recorded on the registry event."),
    reason: str = typer.Option(..., "--reason", help="Why this rollback is happening."),
    to_artifact_id: str | None = typer.Option(
        None,
        "--to-artifact-id",
        help="Reactivate this specific prior artifact instead of falling back to the permanent baseline.",
    ),
) -> None:
    """Retires whatever is currently ACTIVE (marked ROLLED_BACK, not
    RETIRED -- this is an emergency reversal). With no --to-artifact-id,
    the live pipeline falls straight back to the permanent, unmodified
    baseline on its very next run_slate() call -- no other artifact
    needs to exist for this to be safe."""
    with session_scope() as session:
        try:
            event = rollback_active(session, operator=operator, reason=reason, to_artifact_id=to_artifact_id)
        except ValueError as exc:
            typer.echo(f"Cannot roll back: {exc}")
            raise typer.Exit(code=1) from exc
    if event is None:
        typer.echo("Nothing was ACTIVE -- nothing to roll back. The permanent baseline is already serving.")
        return
    typer.echo(f"Rolled back. registry_event_id={event.event_id}")
    if to_artifact_id:
        typer.echo(f"Reactivated artifact_id={to_artifact_id}.")
    else:
        typer.echo("Live pipeline now falls back to the permanent baseline.")


@app.command(name="model-status")
def model_status_cmd(
    history_limit: int = typer.Option(20, "--history-limit", help="How many recent registry events to show."),
) -> None:
    """Shows the model currently serving live predictions (the ACTIVE
    registry artifact, or the permanent baseline if none is ACTIVE --
    registry/service.py's resolve_active_model(), the exact function
    orchestration/run_slate.py itself calls) plus a short history of
    recent registry events, so an operator can see the current state and
    promotion/rollback history without querying the database directly."""
    with session_scope() as session:
        resolved = resolve_active_model(session)
        if resolved.active_artifact_id is None:
            typer.echo(f"ACTIVE: permanent baseline (model_version={resolved.model_version})")
        else:
            artifact = session.get(ModelArtifact, resolved.active_artifact_id)
            if artifact is None:
                raise RuntimeError(
                    f"active_artifact_id={resolved.active_artifact_id} but no matching row exists -- "
                    "should be structurally impossible (model_artifacts is append-only)"
                )
            typer.echo(
                f"ACTIVE: artifact_id={artifact.artifact_id}\n"
                f"  model_version={resolved.model_version}\n"
                f"  trained_at={artifact.trained_at}\n"
                f"  training_dataset_id={artifact.training_dataset_id}\n"
                f"  training_metrics={artifact.training_metrics}"
            )

        events = (
            session.execute(
                select(ModelRegistryEvent).order_by(ModelRegistryEvent.sequence.desc()).limit(history_limit)
            )
            .scalars()
            .all()
        )
        if events:
            typer.echo(f"\nRecent registry events (newest first, up to {history_limit}):")
            for e in events:
                typer.echo(
                    f"  {e.occurred_at.isoformat()}  {e.artifact_id}  "
                    f"{e.from_status or '(none)'} -> {e.to_status}  by {e.operator}"
                    + (f"  ({e.reason})" if e.reason else "")
                )
        else:
            typer.echo("\nNo registry events yet.")


if __name__ == "__main__":
    app()
