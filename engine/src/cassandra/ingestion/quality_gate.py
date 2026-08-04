"""Data-quality checks run while building a snapshot (see
pit/snapshot_builder.py). Pure functions over already as-of-resolved rows
-- no querying here, just judgment -- so they're independently unit
testable without a database.

Each check returns a `QualityFinding` (or None if the check passes
clean). Findings become `snapshot_data_quality` rows and feed into the
eventual projection's `reason_codes` -- never a silent gap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from cassandra.db.models.raw import RawLine, RawProbablePitcher

STALE_THRESHOLD = timedelta(hours=20)
LINE_CONFLICT_WINDOW = timedelta(minutes=30)


@dataclass(frozen=True)
class QualityFinding:
    reason_code: str
    detail: str
    status: Literal["fail", "warn"]


def check_starter_confirmed(probable: RawProbablePitcher | None) -> QualityFinding | None:
    if probable is None:
        return QualityFinding(
            "DATA_MISSING", "No probable pitcher found for this game as of the snapshot cutoff.", "fail"
        )
    if not probable.is_confirmed:
        return QualityFinding(
            "STARTER_UNCONFIRMED",
            f"Probable starter (player_mlb_id={probable.player_mlb_id}) "
            "is not confirmed as of the snapshot cutoff.",
            "warn",
        )
    return None


def check_line_available(lines_latest_first: list[RawLine]) -> QualityFinding | None:
    if not lines_latest_first:
        return QualityFinding(
            "MARKET_CONTEXT_INCOMPLETE",
            "No line observation found for this player/market as of the snapshot cutoff.",
            "fail",
        )
    latest = lines_latest_first[0]
    if latest.is_suspended:
        return QualityFinding(
            "LINE_SUSPENDED", "The latest line observation as of cutoff is marked suspended.", "warn"
        )
    return None


def check_line_conflict(
    lines_latest_first: list[RawLine], window: timedelta = LINE_CONFLICT_WINDOW
) -> QualityFinding | None:
    """Two observations close together in time but disagreeing on the
    line value -- ambiguous, don't silently pick one."""
    if len(lines_latest_first) < 2:
        return None
    latest = lines_latest_first[0]
    for other in lines_latest_first[1:]:
        if latest.line == other.line:
            continue
        if abs((latest.observed_at - other.observed_at).total_seconds()) <= window.total_seconds():
            return QualityFinding(
                "DATA_CONFLICT",
                f"Conflicting line observations within {window}: {latest.line} vs {other.line}.",
                "warn",
            )
    return None


def check_data_stale(
    observed_at: datetime | None,
    cutoff: datetime,
    label: str,
    max_age: timedelta = STALE_THRESHOLD,
) -> QualityFinding | None:
    if observed_at is None:
        return None
    age = cutoff - observed_at
    if age > max_age:
        return QualityFinding(
            "DATA_STALE",
            f"{label} is {age} old as of cutoff (older than the {max_age} threshold).",
            "warn",
        )
    return None
