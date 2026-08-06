from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from cassandra.config import settings

engine = create_engine(
    settings.database_url,
    future=True,
    # pool_pre_ping: test each connection before use so that connections
    # killed by the Postgres provider's idle-timeout (AdminShutdown) are
    # detected and recycled automatically instead of raising mid-request.
    pool_pre_ping=True,
    # pool_recycle: proactively replace connections older than 4.5 minutes,
    # well under the typical provider idle-timeout (Neon: 5 min default).
    pool_recycle=270,
)
# expire_on_commit=False: both the CLI and callers of orchestration's
# run_slate()/grade_slate_run() read attributes off ORM objects (e.g.
# Projection.player_id) after session_scope()'s commit, once the session
# is already closed -- the default expire-on-commit behavior would force
# a lazy reload at that point and raise (no session to reload from).
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, future=True, expire_on_commit=False
)


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """One session per call, committed on success and rolled back on any
    exception -- the shared transaction-lifecycle used by both the
    FastAPI dependency below and the CLI (cli/main.py), so neither route
    nor command code needs to call commit()/rollback() itself."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency wrapper around session_scope()."""
    with session_scope() as session:
        yield session
