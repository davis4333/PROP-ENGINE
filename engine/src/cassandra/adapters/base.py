"""The pluggable source-adapter contract (see the cassandra-data-adapter
skill for the how-to).

Every adapter -- real or stand-in -- implements `fetch()` and NEVER raises
for "no data available." Absence is a first-class outcome
(`AdapterFetchResult.is_available=False` + `warnings`), not an exception,
so the pipeline can turn it into a visible reason code (DATA_MISSING,
etc.) instead of crashing or silently omitting the gap.

`RawRecord.fields` must use exactly the target raw model's column names
(minus `raw_id`/`source_id`/`ingested_at`/`observed_at`/`payload`, which
`ingestion/ingest_service.py` fills in generically) -- e.g. for
`RawLine`, `fields` looks like
`{"mlb_game_pk": ..., "player_mlb_id": ..., "market": ..., "line": ...}`.
This lets ingestion construct `adapter.raw_model(**record.fields, ...)`
without a big per-adapter dispatch table.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, ClassVar, Literal

from cassandra.db.base import Base

AdapterKind = Literal["schedule", "pitcher_stats", "weather", "park", "umpire", "lines"]


@dataclass(frozen=True)
class RawRecord:
    fields: dict[str, Any]
    observed_at: datetime
    payload: dict[str, Any]
    record_hash: str | None = None


@dataclass(frozen=True)
class AdapterFetchResult:
    records: list[RawRecord]
    fetched_at: datetime
    is_available: bool = True
    warnings: list[str] = field(default_factory=list)


class SourceAdapter(ABC):
    kind: ClassVar[AdapterKind]
    source_name: ClassVar[str]
    adapter_version: ClassVar[str]
    raw_model: ClassVar[type[Base]]

    @abstractmethod
    def fetch(self, *, slate_date: date, as_of: datetime | None = None, **kwargs: Any) -> AdapterFetchResult:
        """Fetch this slate's records for this source.

        `as_of` bounds how "current" the fetch should be (mainly relevant
        to adapters hitting a live feed that could otherwise return data
        from after a historical replay's cutoff); adapters that can't
        honor it should just ignore it rather than raise.

        `**kwargs` carries adapter-specific context that a single
        `(slate_date, as_of)` pair can't express -- e.g. the pitcher-game-
        logs adapter needs `player_mlb_ids`, the weather adapter needs
        `venues`. Every such parameter must have a safe empty default
        (adapter returns `is_available=False` with a warning, never
        raises, if the context it needs wasn't supplied).

        Must never raise for "no data available" -- catch adapter-specific
        failure modes (HTTP errors, empty responses, missing optional
        context) and return `AdapterFetchResult(records=[],
        is_available=False, warnings=[...])` instead.
        """
        raise NotImplementedError
