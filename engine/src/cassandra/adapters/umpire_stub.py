"""Umpire-assignment stub adapter -- no reliable free source exists (see
CURRENT_STATE_AUDIT.md). Always reports unavailable so the gap is visible
and auditable rather than silently absent; the pipeline must never block
on this being missing (umpire context is a soft signal, not required for
a projection to qualify).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from cassandra.adapters.base import AdapterFetchResult, SourceAdapter
from cassandra.db.models.raw import RawUmpireAssignment


class UmpireStubAdapter(SourceAdapter):
    kind = "umpire"
    source_name = "umpire_stub"
    adapter_version = "0.1.0"
    raw_model = RawUmpireAssignment

    def fetch(self, *, slate_date: date, as_of: datetime | None = None, **kwargs: Any) -> AdapterFetchResult:
        return AdapterFetchResult(
            records=[],
            fetched_at=datetime.now(UTC),
            is_available=False,
            warnings=[
                "No reliable free umpire-assignment source is available; "
                "this adapter is a permanent stub until a real source is confirmed."
            ],
        )
