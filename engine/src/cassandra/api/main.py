"""The FastAPI app. See docs/adr/0012 for why the frontend is limited to
Today/Ledger/Admin -- the API surface mirrors that same scope."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cassandra.api.routers import admin, ledger, today

app = FastAPI(title="Cassandra", version="0.1.0")

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
