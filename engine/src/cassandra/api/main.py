"""The FastAPI app. See docs/adr/0012 for why the frontend is limited to
Today/Ledger/Admin -- the API surface mirrors that same scope."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cassandra.api.routers import admin, ledger, today
from cassandra.config import admin_secret_is_weak, is_production_environment, settings
from cassandra.orchestration.scheduler import start_background_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Phase 8 security gate: a real deployment must refuse to serve
    # traffic at all on a weak/placeholder admin secret (ADR 0011's own
    # auth is a shared-secret header, not real auth -- a guessable value
    # is the whole ballgame). Deliberately fails loud and fast (crashes
    # startup) rather than logging a warning and continuing, since a
    # warning is easy to miss in deploy logs and this is the one thing
    # standing between the Admin page and the public internet.
    if is_production_environment() and admin_secret_is_weak(settings.admin_shared_secret):
        raise RuntimeError(
            "Refusing to start: ADMIN_SHARED_SECRET is missing, a known placeholder "
            "value, or too short for a production deployment. Set a real, unique, "
            "high-entropy secret (e.g. `openssl rand -hex 32`) via the ADMIN_SHARED_SECRET "
            "environment variable / Replit Secret before deploying."
        )

    # No-op unless settings.auto_scheduler_enabled -- see
    # orchestration/scheduler.py. Confirmed this does NOT fire for
    # `TestClient(app)` used without a `with` block (this repo's API test
    # fixture), so the test suite never starts it regardless.
    stop_event = start_background_scheduler()
    try:
        yield
    finally:
        stop_event.set()


app = FastAPI(title="Cassandra", version="0.1.0", lifespan=lifespan)

# Permissive CORS is a local/demo convenience, not a production posture --
# see CURRENT_STATE_AUDIT.md. Tighten to the real frontend origin before
# any non-local deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(today.router)
app.include_router(ledger.router)
app.include_router(admin.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
