"""FastAPI dependencies: the request-scoped DB session and the admin
shared-secret gate (ADR 0011 -- explicitly a demo-only placeholder, not
production authentication)."""

from __future__ import annotations

import hmac
import logging
import threading
import time
from collections.abc import Generator

from fastapi import Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from cassandra.config import settings
from cassandra.db.session import get_session

logger = logging.getLogger(__name__)


def get_db() -> Generator[Session, None, None]:
    yield from get_session()


# Bare-minimum brute-force throttle for the admin gate -- ADR 0011 is
# explicit this is demo-only auth, not production authentication, but
# once genuinely live and publicly reachable (see CURRENT_STATE_AUDIT.md)
# an unthrottled string-equality check over a weak/guessable secret is a
# real, unbounded brute-force target, not just a theoretical one. This is
# in-process/in-memory only -- consistent with the rest of this
# codebase's single-instance assumption (see orchestration/scheduler.py's
# own documented limitation) -- and resets on restart; it is not a
# substitute for a real secret or real auth, just a floor under it.
_FAILURE_LIMIT = 10
_LOCKOUT_SECONDS = 300
_lock = threading.Lock()
_failures_by_client: dict[str, list[float]] = {}


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _is_locked_out(client_key: str) -> bool:
    cutoff = time.monotonic() - _LOCKOUT_SECONDS
    with _lock:
        recent = [t for t in _failures_by_client.get(client_key, []) if t > cutoff]
        _failures_by_client[client_key] = recent
        return len(recent) >= _FAILURE_LIMIT


def _record_failure(client_key: str) -> None:
    with _lock:
        _failures_by_client.setdefault(client_key, []).append(time.monotonic())


def require_admin(request: Request, x_admin_secret: str | None = Header(default=None)) -> None:
    client_key = _client_key(request)
    if _is_locked_out(client_key):
        # Not re-logged on every locked-out retry (that's just the same
        # already-recorded failure streak hitting the wall) -- the
        # individual failures that got it there were already logged below.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed admin auth attempts -- try again later",
        )
    # hmac.compare_digest, not `!=` -- a plain string comparison short-
    # circuits on the first differing byte, which is a real (if narrow)
    # timing side-channel for guessing a shared secret over the network.
    if not x_admin_secret or not hmac.compare_digest(x_admin_secret, settings.admin_shared_secret):
        _record_failure(client_key)
        # Operational audit trail for a real deployment (Phase 8) --
        # never logs the attempted secret value itself, only that an
        # attempt happened and from where, so this can't itself become a
        # secrets leak via log aggregation.
        logger.warning("admin auth failed: client=%s path=%s", client_key, request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid X-Admin-Secret header"
        )
