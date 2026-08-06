"""The FastAPI app. See docs/adr/0012 for why the frontend is limited to
Today/Ledger/Admin -- the API surface mirrors that same scope."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
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

# Permissive by default (settings.allowed_origins, "*") -- a local/demo
# convenience that's also safe in the actual Replit deployment topology
# (the engine binds 127.0.0.1-only there; scripts/replit_start.sh), since
# no browser can reach it cross-origin at all in that setup. A real non-
# Replit/non-proxied deployment should set ALLOWED_ORIGINS to a real
# comma-separated allowlist -- see config.py.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Phase 8 security hardening. No CSRF-token mechanism here, deliberately:
# classic CSRF exploits a browser AUTOMATICALLY attaching credentials
# (cookies) to a cross-origin request the victim didn't intend to make.
# This app has no cookie-based session at all -- api/deps.py's
# require_admin reads a custom X-Admin-Secret HEADER, which a browser
# never attaches automatically, and which a malicious page cannot read or
# set on the victim's behalf without already knowing the secret (same-
# origin policy blocks reading another origin's sessionStorage, and
# "set an arbitrary header on a cross-origin request" isn't something a
# browser lets a page do at all). A CSRF token would add complexity
# without closing a gap that exists here -- see CURRENT_STATE_AUDIT.md
# for this reasoning recorded outside code too, so it's not silently
# reintroduced later as an unexplained gap.
@app.middleware("http")
async def _security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


app.include_router(today.router)
app.include_router(ledger.router)
app.include_router(admin.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
