from cassandra.config import Settings, admin_secret_is_weak, is_production_environment, settings


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


# --- weak admin secret detection ------------------------------------------


def test_known_placeholder_secrets_are_weak():
    for value in ("test", "change-me-dev-only", "changeme", "admin", "password", "secret", ""):
        assert admin_secret_is_weak(value), f"{value!r} should be flagged weak"


def test_known_placeholder_secrets_are_weak_case_insensitively():
    assert admin_secret_is_weak("TEST")
    assert admin_secret_is_weak("Change-Me-Dev-Only")


def test_short_secret_is_weak_even_if_not_a_known_placeholder():
    assert admin_secret_is_weak("abc123")


def test_long_random_secret_is_not_weak():
    assert not admin_secret_is_weak("f3a9c1e7b2d84a6f9e0c1b3d5a7f9e1c3b5d7f9a1c3e5b7d9f1a3c5e7b9d1f3a")


def test_secret_just_under_the_length_floor_is_weak():
    assert admin_secret_is_weak("a" * 15)


def test_secret_at_the_length_floor_and_not_a_placeholder_is_not_weak():
    assert not admin_secret_is_weak("a" * 16)


# --- production environment detection --------------------------------------


def test_production_mode_setting_forces_production_environment(monkeypatch):
    monkeypatch.setattr(settings, "production_mode", True)
    monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)
    assert is_production_environment() is True


def test_replit_deployment_env_var_implies_production_environment(monkeypatch):
    monkeypatch.setattr(settings, "production_mode", False)
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")
    assert is_production_environment() is True


def test_neither_signal_present_is_not_production(monkeypatch):
    monkeypatch.setattr(settings, "production_mode", False)
    monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)
    assert is_production_environment() is False


# --- CORS allowed-origins parsing -------------------------------------------


def test_default_allowed_origins_is_wildcard():
    assert Settings().allowed_origins_list == ["*"]


def test_allowed_origins_splits_on_comma_and_strips_whitespace():
    s = Settings(allowed_origins="https://cassandrahits.replit.app, https://example.com")
    assert s.allowed_origins_list == ["https://cassandrahits.replit.app", "https://example.com"]


def test_allowed_origins_ignores_empty_entries():
    s = Settings(allowed_origins="https://example.com,,  ,")
    assert s.allowed_origins_list == ["https://example.com"]
