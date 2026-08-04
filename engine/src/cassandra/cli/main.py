"""Operator CLI (typer). Thin wrappers over the same service/orchestration
functions the API and tests use -- no logic lives here, only argument
parsing and printed summaries. Each command opens one db.session_scope()
per invocation: commits on success, rolls back and exits non-zero on any
exception.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import typer

from cassandra.db.session import session_scope
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


if __name__ == "__main__":
    app()
