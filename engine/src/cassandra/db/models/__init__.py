"""Import every model module so Alembic autogenerate / Base.metadata sees all tables."""

from cassandra.db.models import (  # noqa: F401
    audit,
    features,
    grading,
    identity,
    pipeline,
    projection,
    raw,
    snapshot,
    sources,
)
