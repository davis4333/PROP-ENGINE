"""Shared pytest fixtures. `db_session` gives every test a real Postgres
session (against DATABASE_URL, migrated schema expected) wrapped in a
transaction that's rolled back after the test -- fast, isolated, and
exercises the actual immutability grants/constraints rather than mocking
them away.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from cassandra.config import settings


@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine(settings.database_url, future=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:
    connection = db_engine.connect()
    transaction = connection.begin()
    session_factory = sessionmaker(bind=connection, future=True)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
