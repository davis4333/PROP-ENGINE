"""Manual/fixture line importer -- stands in for a real Underdog adapter.

Underdog has no free public API, and the handbook explicitly flags its
real acquisition method/ToS as legally unresolved (see
docs/DECISION_LEDGER.csv). Scraping is out. This adapter instead reads a
drop-folder of JSON files (default `engine/data/lines_drops/`, override
via `drop_dir=` kwarg) that an operator populates by hand -- or that the
fixture demo slate ships pre-populated -- conforming to the exact schema
a real Underdog adapter would need to produce:

    {
      "slate_date": "2023-06-15",
      "observed_at": "2023-06-15T15:00:00Z",   // file-level default
      "lines": [
        {
          "mlb_game_pk": 717753,
          "player_mlb_id": 579328,
          "market": "pitcher_strikeouts",
          "line": 5.5,
          "over_price": null,
          "under_price": null,
          "is_suspended": false,
          "observed_at": "2023-06-15T16:00:00Z"   // optional per-entry override
        }
      ]
    }

Swapping in a real Underdog adapter later means replacing only this
file's `fetch()` body (HTTP call instead of a folder read) -- the output
contract (`AdapterFetchResult` of `RawRecord`s targeting `raw_lines`)
stays identical, so nothing downstream changes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from cassandra.adapters.base import AdapterFetchResult, RawRecord, SourceAdapter
from cassandra.db.models.raw import RawLine

DEFAULT_DROP_DIR = Path(__file__).resolve().parents[3] / "data" / "lines_drops"


class LinesManualAdapter(SourceAdapter):
    kind = "lines"
    source_name = "lines_manual"
    adapter_version = "0.1.0"
    raw_model = RawLine

    def __init__(self, drop_dir: Path | None = None) -> None:
        self._drop_dir = drop_dir or DEFAULT_DROP_DIR

    def fetch(self, *, slate_date: date, as_of: datetime | None = None, **kwargs: Any) -> AdapterFetchResult:
        fetched_at = datetime.now(UTC)
        drop_dir: Path = kwargs.get("drop_dir") or self._drop_dir
        if not drop_dir.exists():
            return AdapterFetchResult(
                records=[],
                fetched_at=fetched_at,
                is_available=False,
                warnings=[f"Lines drop folder does not exist: {drop_dir}"],
            )

        records: list[RawRecord] = []
        warnings: list[str] = []
        matched_any_file = False
        for path in sorted(drop_dir.glob("*.json")):
            try:
                doc = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                warnings.append(f"Could not read {path.name}: {exc}")
                continue

            if doc.get("slate_date") != slate_date.isoformat():
                continue
            matched_any_file = True

            default_observed_raw = doc.get("observed_at")
            default_observed = _parse_dt(default_observed_raw) if default_observed_raw else fetched_at

            for entry in doc.get("lines", []):
                observed_raw = entry.get("observed_at")
                observed_at = _parse_dt(observed_raw) if observed_raw else default_observed
                fields = {
                    "mlb_game_pk": entry["mlb_game_pk"],
                    "player_mlb_id": entry["player_mlb_id"],
                    "market": entry.get("market", "pitcher_strikeouts"),
                    "line": entry["line"],
                    "over_price": entry.get("over_price"),
                    "under_price": entry.get("under_price"),
                    "is_suspended": entry.get("is_suspended", False),
                }
                records.append(
                    RawRecord(
                        fields=fields,
                        observed_at=observed_at,
                        payload=entry,
                        record_hash=_hash_entry(entry),
                    )
                )

        if not matched_any_file:
            return AdapterFetchResult(
                records=[],
                fetched_at=fetched_at,
                is_available=False,
                warnings=[f"No lines drop file found for slate_date={slate_date.isoformat()}"],
            )
        return AdapterFetchResult(records=records, fetched_at=fetched_at, warnings=warnings)


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _hash_entry(entry: dict[str, Any]) -> str:
    canonical = json.dumps(entry, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
