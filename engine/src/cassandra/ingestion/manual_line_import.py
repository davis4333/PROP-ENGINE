"""Admin-facing manual line import -- resolves pasted lines (player name
+ line + prices) against a slate's real confirmed probable pitchers and
writes matched entries as `raw_lines` rows, the same contract
`adapters/lines_manual.py`'s file-based stand-in produces.

Exists because that drop-folder mechanism requires filesystem access to
the running server, which an admin operator on a deployed instance
(Replit) doesn't have -- this exposes the same underlying capability
(`LinesManualAdapter`'s `raw_lines` contract; still not a real Underdog
HTTP acquisition, which stays unresolved/out of scope per CLAUDE.md's
do-not-scrape-Underdog rule and `docs/DECISION_LEDGER.csv`) as an admin
action instead of a file drop.

Matching reuses the same by-name-against-today's-confirmed-starters
approach and ambiguous-name-collision handling
`adapters/lines_odds_api.py`'s real odds-vendor integration already
uses -- a bare name match can't disambiguate two same-named confirmed
starters, so an ambiguous entry is reported, never guessed at.
`_current_probables_context` deliberately mirrors (does not import)
`orchestration/run_slate.py`'s `_ingest_lines` probables-context
construction -- a small, intentional duplication rather than reworking
already-tested live-pipeline code for this admin-only feature.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cassandra.adapters.base import AdapterFetchResult, RawRecord, SourceAdapter
from cassandra.db.models.identity import Player
from cassandra.db.models.raw import RawLine, RawProbablePitcher
from cassandra.ingestion.ingest_service import IngestResult, ingest
from cassandra.pit.asof import all_as_of
from cassandra.pit.snapshot_builder import games_for_slate_date

MANUAL_LINE_IMPORT_SOURCE_NAME = "lines_manual_admin_import"
MANUAL_LINE_IMPORT_ADAPTER_VERSION = "0.1.0"
MARKET_DEFAULT = "pitcher_strikeouts"


@dataclass(frozen=True)
class LineImportEntry:
    player_name: str
    line: float
    over_price: float | None = None
    under_price: float | None = None
    market: str = MARKET_DEFAULT


@dataclass(frozen=True)
class MatchedEntry:
    entry: LineImportEntry
    player_mlb_id: int
    mlb_game_pk: int
    is_possible_duplicate: bool


@dataclass(frozen=True)
class UnmatchedEntry:
    entry: LineImportEntry
    reason: str


@dataclass(frozen=True)
class LineImportPreview:
    slate_date: date
    matched: list[MatchedEntry]
    unmatched: list[UnmatchedEntry]


def _current_probables_context(
    session: Session, slate_date: date, as_of: datetime | None = None
) -> list[dict[str, Any]]:
    cutoff = as_of or datetime.now(UTC)
    games = games_for_slate_date(session, slate_date)
    probables: list[RawProbablePitcher] = []
    for game in games:
        probables.extend(all_as_of(session, RawProbablePitcher, {"mlb_game_pk": game.mlb_game_pk}, cutoff))

    player_mlb_ids = sorted({p.player_mlb_id for p in probables})
    names_by_mlb_id: dict[int, str] = {}
    if player_mlb_ids:
        rows = session.execute(select(Player).where(Player.mlb_person_id.in_(player_mlb_ids))).scalars()
        names_by_mlb_id = {r.mlb_person_id: r.full_name for r in rows if r.mlb_person_id is not None}

    return [
        {
            "player_mlb_id": p.player_mlb_id,
            "mlb_game_pk": p.mlb_game_pk,
            "full_name": names_by_mlb_id[p.player_mlb_id],
        }
        for p in probables
        if p.player_mlb_id in names_by_mlb_id
    ]


def _match_entries(
    entries: list[LineImportEntry], probables_context: list[dict[str, Any]]
) -> tuple[list[tuple[LineImportEntry, dict[str, Any]]], list[UnmatchedEntry]]:
    by_name: dict[str, list[dict[str, Any]]] = {}
    for p in probables_context:
        by_name.setdefault(p["full_name"], []).append(p)

    matched: list[tuple[LineImportEntry, dict[str, Any]]] = []
    unmatched: list[UnmatchedEntry] = []
    for entry in entries:
        candidates = by_name.get(entry.player_name)
        if not candidates:
            unmatched.append(
                UnmatchedEntry(
                    entry=entry,
                    reason=f"No confirmed starter named '{entry.player_name}' found for this slate",
                )
            )
            continue
        if len(candidates) > 1:
            unmatched.append(
                UnmatchedEntry(
                    entry=entry,
                    reason=(
                        f"Ambiguous: {len(candidates)} confirmed starters today are named "
                        f"'{entry.player_name}' -- cannot safely attach a line to either"
                    ),
                )
            )
            continue
        matched.append((entry, candidates[0]))
    return matched, unmatched


def _existing_line_today(session: Session, *, mlb_game_pk: int, player_mlb_id: int, market: str) -> bool:
    """Informational duplicate check -- an existing `raw_lines` row for
    this exact player/game/market ingested earlier today from ANY
    source. Not blocking: `raw_lines` is append-only and more than one
    line across a day is an expected, normal outcome (e.g. a vendor's
    line plus a manual correction), just surfaced so an operator isn't
    surprised by it."""
    today_start = datetime.combine(datetime.now(UTC).date(), datetime.min.time(), tzinfo=UTC)
    stmt = (
        select(RawLine.raw_id)
        .where(
            RawLine.mlb_game_pk == mlb_game_pk,
            RawLine.player_mlb_id == player_mlb_id,
            RawLine.market == market,
            RawLine.ingested_at >= today_start,
        )
        .limit(1)
    )
    return session.execute(stmt).first() is not None


def preview_line_import(
    session: Session, slate_date: date, entries: list[LineImportEntry], as_of: datetime | None = None
) -> LineImportPreview:
    """Pure preview -- resolves each entry against today's real confirmed
    starters and flags likely duplicates, without writing anything."""
    probables_context = _current_probables_context(session, slate_date, as_of)
    matched_pairs, unmatched = _match_entries(entries, probables_context)
    matched = [
        MatchedEntry(
            entry=entry,
            player_mlb_id=probable["player_mlb_id"],
            mlb_game_pk=probable["mlb_game_pk"],
            is_possible_duplicate=_existing_line_today(
                session,
                mlb_game_pk=probable["mlb_game_pk"],
                player_mlb_id=probable["player_mlb_id"],
                market=entry.market,
            ),
        )
        for entry, probable in matched_pairs
    ]
    return LineImportPreview(slate_date=slate_date, matched=matched, unmatched=unmatched)


class ManualLineImportAdapter(SourceAdapter):
    """Wraps the matching logic in the standard adapter contract so
    `commit_line_import` can reuse `ingestion/ingest_service.py`'s
    write-path (raw row + source_health + audit_event), identical to
    every other source. Takes already-resolved `probables` context via
    kwargs (no DB access of its own), consistent with the rest of the
    adapter contract -- callers do the DB lookup, adapters only shape
    data."""

    kind = "lines"
    source_name = MANUAL_LINE_IMPORT_SOURCE_NAME
    adapter_version = MANUAL_LINE_IMPORT_ADAPTER_VERSION
    raw_model = RawLine

    def fetch(self, *, slate_date: date, as_of: datetime | None = None, **kwargs: Any) -> AdapterFetchResult:
        fetched_at = datetime.now(UTC)
        entries: list[LineImportEntry] = kwargs.get("entries") or []
        probables_context: list[dict[str, Any]] = kwargs.get("probables") or []

        if not entries:
            return AdapterFetchResult(
                records=[], fetched_at=fetched_at, is_available=False, warnings=["No line entries supplied"]
            )

        matched_pairs, unmatched = _match_entries(entries, probables_context)
        records = [
            RawRecord(
                fields={
                    "mlb_game_pk": probable["mlb_game_pk"],
                    "player_mlb_id": probable["player_mlb_id"],
                    "market": entry.market,
                    "line": entry.line,
                    "over_price": entry.over_price,
                    "under_price": entry.under_price,
                    "is_suspended": False,
                },
                observed_at=fetched_at,
                payload={"player_name": entry.player_name, "imported_via": "admin_manual_line_import"},
            )
            for entry, probable in matched_pairs
        ]
        warnings = [f"{u.entry.player_name}: {u.reason}" for u in unmatched]
        if not records:
            return AdapterFetchResult(
                records=[],
                fetched_at=fetched_at,
                is_available=False,
                warnings=warnings or ["No entries matched a confirmed starter"],
            )
        return AdapterFetchResult(records=records, fetched_at=fetched_at, warnings=warnings)


def commit_line_import(
    session: Session,
    slate_date: date,
    entries: list[LineImportEntry],
    *,
    run_id: str | None = None,
    as_of: datetime | None = None,
) -> IngestResult:
    """Resolves and writes matched entries as real `raw_lines` rows via
    the standard ingest path. Unmatched entries are never written or
    guessed at -- they come back as `IngestResult.warnings`, one line per
    entry, so the caller can show exactly what wasn't imported and why."""
    cutoff = as_of or datetime.now(UTC)
    probables_context = _current_probables_context(session, slate_date, cutoff)
    return ingest(
        session,
        ManualLineImportAdapter(),
        slate_date=slate_date,
        as_of=cutoff,
        run_id=run_id,
        entries=entries,
        probables=probables_context,
    )


__all__ = [
    "MANUAL_LINE_IMPORT_SOURCE_NAME",
    "LineImportEntry",
    "LineImportPreview",
    "ManualLineImportAdapter",
    "MatchedEntry",
    "UnmatchedEntry",
    "commit_line_import",
    "preview_line_import",
]
