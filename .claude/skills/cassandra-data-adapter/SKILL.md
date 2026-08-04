---
name: cassandra-data-adapter
description: How to build or modify a Cassandra SourceAdapter conforming to the adapters/base.py contract — fetch(slate_date, as_of) returning AdapterFetchResult, never raising for "no data available," natural_key/observed_at/payload per record, registration in the sources table, and wiring into ingestion/ingest_service.py. Use when adding a new data source, editing an existing adapter (schedule, pitcher stats, weather, park factors, umpire, lines), or reviewing adapter code.
---

# Building a Cassandra SourceAdapter

Every data source enters the system through a `SourceAdapter` conforming to
the contract at `engine/src/cassandra/adapters/base.py`. This is the seam
that lets a real paid vendor (or a real ToS-compliant Underdog adapter)
swap in later without touching ingestion, snapshotting, features, or the
decision engine.

## The contract

```python
class SourceAdapter(ABC):
    source_id: str          # must match a row in the `sources` table
    kind: str                # one of SOURCE_KINDS in db/models/sources.py:
                              # "schedule" | "pitcher_stats" | "weather" |
                              # "park" | "umpire" | "lines"

    @abstractmethod
    async def fetch(self, slate_date: date, as_of: datetime) -> AdapterFetchResult:
        ...

class RawRecord:
    natural_key: str     # e.g. f"{mlb_game_pk}:{player_mlb_id}" — used for
                          # dedup/entity matching, NOT a raw_id
    observed_at: datetime # the source's claimed effective/as-of time
    payload: dict         # raw JSON as received, stored verbatim in JSONB

class AdapterFetchResult:
    is_available: bool
    records: list[RawRecord]
    warnings: list[str]
```

## The one rule that matters most: never raise for "no data"

An adapter **must never raise an exception because a source has no data for
this slate** — a game with no probable pitcher yet, an umpire feed with
nothing posted, a weather API returning an empty forecast window are all
normal, expected states, not adapter failures. Instead:

- Return `AdapterFetchResult(is_available=False, records=[], warnings=[...])`
  with a human-readable warning explaining what's missing.
- Reserve raising for genuine adapter-cannot-function failures (network
  timeout after retries, malformed response the adapter can't parse at
  all, auth failure) — and even then, prefer surfacing this through
  `source_health` (`db/models/sources.py`: `last_failure_at`,
  `consecutive_failures`) so `ingest_service.py` can decide how to
  degrade, rather than crashing the whole slate ingest.

Downstream, the pipeline turns `is_available=False` into a visible
`DATA_MISSING` reason code on affected projections (Appendix A of the
handbook) — never a silent omission and never a crash. If your adapter
raises for a missing-data case, you have broken that contract even if the
adapter code is otherwise correct.

## Per-record fields

For every record your adapter returns:

- `natural_key` — the identity the record represents (e.g. game+player),
  used to correlate across `ingested_at` versions of "the same fact," not
  a database primary key.
- `observed_at` — the source's own claimed as-of time. If the source
  doesn't provide one, use the fetch time — but say so in a code comment,
  since this directly feeds the ADR 0001 cutoff filter and a wrong
  `observed_at` is a leakage risk, not a cosmetic detail.
- `payload` — the raw response as received (or the minimal normalized
  subset), stored in the table's `payload JSONB` column verbatim, so a
  parsing bug discovered later can be replayed without re-fetching.

`ingested_at` is **not** set by the adapter — it's the raw table's
`server_default=func.now()`, i.e. the physical write time. Don't try to
backfill or override it from adapter code; that would defeat the leakage
gate ADR 0001 depends on.

## Existing patterns to follow

- **`LinesManualAdapter`** (stand-in for a real Underdog adapter) reads a
  drop-folder of JSON/CSV files matching the exact schema a real HTTP
  adapter would need (`raw_lines`: `mlb_game_pk`, `player_mlb_id`,
  `market`, `line`, `over_price`, `under_price`, `is_suspended`). Do not
  build a scraper against Underdog — their real acquisition method is
  explicitly unresolved per the handbook and `CLAUDE.md`'s do-not-do list.
  A real adapter later only replaces this one's `fetch()` body; nothing
  downstream changes.
- **`UmpireStubAdapter`** always returns `is_available=False` with a
  warning — there is no reliable free umpire source. This is a permanent,
  intentional stand-in (not a TODO to "eventually" implement with scraping)
  until a real source is confirmed. Never make this adapter block the
  pipeline (`engine/tests/pit/` includes a case asserting exactly this).

## Wiring a new adapter in

1. Add a row to `sources` (`db/models/sources.py`) — `source_id`, `kind`
   (must be one of `SOURCE_KINDS`), `adapter_version`.
2. Implement `fetch()` in `engine/src/cassandra/adapters/<name>.py`,
   taking an injectable HTTP client (see the plan's fixture-testing
   pattern) so tests exercise real parsing logic against fixtures rather
   than bypassing the adapter.
3. Register it with `ingestion/ingest_service.py` so it runs during the
   `INGEST` pipeline stage and its per-record writes land in the
   corresponding `raw_*` table with `source_id` set.
4. On fetch failure/degradation, update `source_health` so the Admin page
   (`GET /api/admin/status`) can show it — this is the visible
   error/stale-data behavior the Definition of Done requires.
5. Add adapter tests under fixtures (mirroring
   `engine/tests/fixtures/slate_2023_06_15/` per ADR 0013's historical
   fixture date), including the "no data available" path explicitly — a
   missing test for that path is a common way this contract gets silently
   broken later.

## Common mistakes to catch in review

- Adapter raises on empty/missing upstream data instead of returning
  `is_available=False`.
- `observed_at` silently defaults to `ingested_at`/now without a comment
  explaining the source doesn't provide its own as-of time.
- A new adapter kind not added to `SOURCE_KINDS` in
  `db/models/sources.py`, so the DB CHECK constraint would reject the
  `sources` row.
- Any HTTP call to Underdog (or scraping of any kind) — this is a hard
  no per `CLAUDE.md`, not just a style preference.
