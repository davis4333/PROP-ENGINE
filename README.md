# Cassandra / CassandraHits — Engine

MLB player-prop decision and transparency platform. Pitcher strikeouts first.
Point-in-time data integrity, immutable projection ledger, honest grading.
See `docs/handbook.md` for the full product/engineering spec and
`CURRENT_STATE_AUDIT.md` for what's actually built vs. stubbed today.

This is **Phase 1 (Foundation)** of the vertical-slice build: repository
scaffold, database schema, the pluggable source-adapter contract, and one
working adapter end-to-end (static park factors). Ingestion of real MLB/
weather/lines data, the point-in-time snapshot builder, the baseline model,
the decision engine, and the public/admin UI are **not yet built** — see
`CURRENT_STATE_AUDIT.md` for the phased plan.

## Local setup

Requirements: Docker, Python 3.11+, `uv` or `pip`.

```bash
cp .env.example .env

# Start Postgres (and the engine API, once there's more to serve)
docker compose up -d postgres

# Install engine deps
cd engine
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Apply migrations
alembic upgrade head

# Run tests
pytest

# Run the API
uvicorn cassandra.api.main:app --reload
# -> GET http://localhost:8000/api/admin/status

# Ingest the one working adapter (static park factors) via the CLI
python -m cassandra.cli.main ingest park-factors
```

## Repository layout

```
engine/   Python (FastAPI + SQLAlchemy + Alembic) — the data/model/decision engine
web/      Next.js frontend (Today / Ledger / Admin) — not yet built, Phase 4
docs/     Product handbook copy + architecture decision records
```
