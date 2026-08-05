from cassandra.config import Settings


def test_postgresql_scheme_is_rewritten_to_psycopg_driver():
    settings = Settings(database_url="postgresql://user:pw@host/db")
    assert settings.database_url == "postgresql+psycopg://user:pw@host/db"


def test_postgres_scheme_is_rewritten_to_psycopg_driver():
    # Heroku-style hosts (and some managed Postgres providers) hand out
    # "postgres://" rather than "postgresql://".
    settings = Settings(database_url="postgres://user:pw@host/db")
    assert settings.database_url == "postgresql+psycopg://user:pw@host/db"


def test_already_correct_driver_scheme_is_left_alone():
    settings = Settings(database_url="postgresql+psycopg://user:pw@host/db")
    assert settings.database_url == "postgresql+psycopg://user:pw@host/db"
