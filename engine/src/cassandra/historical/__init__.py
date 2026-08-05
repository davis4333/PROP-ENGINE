"""Historical MLB data backfill (2023-present) -- see
docs/HISTORICAL_BACKFILL_DESIGN.md. Deliberately a separate subsystem
from the live daily pipeline (orchestration/run_slate.py): it writes to
its own tables (db/models/historical.py), never touches the live raw_*
tables or pit/asof.py's leakage gate, and is driven by its own CLI
commands (cli/main.py's `backfill-mlb` family), not the scheduler.
"""
