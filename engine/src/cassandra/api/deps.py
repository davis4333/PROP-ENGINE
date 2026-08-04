"""FastAPI dependencies: the request-scoped DB session and the admin
shared-secret gate (ADR 0011 -- explicitly a demo-only placeholder, not
production authentication)."""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Header, HTTPException, status
from sqlalchemy.orm import Session

from cassandra.config import settings
from cassandra.db.session import get_session


def get_db() -> Generator[Session, None, None]:
    yield from get_session()


def require_admin(x_admin_secret: str | None = Header(default=None)) -> None:
    if not x_admin_secret or x_admin_secret != settings.admin_shared_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid X-Admin-Secret header"
        )
