.PHONY: help engine-install web-install install \
        lint format format-check typecheck security guardrails \
        test-engine test-web test migrate-check db-up db-down \
        build-web verify clean

ENGINE_DIR := engine
WEB_DIR := web
ENGINE_VENV := $(ENGINE_DIR)/.venv
ENGINE_PY := $(ENGINE_VENV)/bin/python
UV := uv

help:
	@echo "Cassandra engine — make targets:"
	@echo "  install          - install engine (uv) and web (pnpm) dependencies"
	@echo "  lint             - ruff (engine) + eslint (web)"
	@echo "  format-check     - ruff format --check (engine) + prettier --check (web)"
	@echo "  typecheck        - mypy (engine) + tsc --noEmit (web)"
	@echo "  security         - bandit + pip-audit (engine)"
	@echo "  guardrails       - scripts/guardrails.py static safeguard checks"
	@echo "  test-engine      - pytest (engine + scripts)"
	@echo "  test-web         - vitest + playwright (web)"
	@echo "  migrate-check    - apply alembic migrations against DATABASE_URL"
	@echo "  build-web        - next build"
	@echo "  verify           - the full gate: everything above, in order"

# --- setup -------------------------------------------------------------

engine-install:
	cd $(ENGINE_DIR) && $(UV) venv --python 3.12 .venv --allow-existing
	$(UV) pip install -e "$(ENGINE_DIR)[dev]" --python $(ENGINE_PY)

web-install:
	cd $(WEB_DIR) && pnpm install

install: engine-install web-install

# --- lint / format / typecheck / security -------------------------------

lint:
	$(ENGINE_PY) -m ruff check $(ENGINE_DIR)/src $(ENGINE_DIR)/tests scripts
	cd $(WEB_DIR) && pnpm run lint

format-check:
	$(ENGINE_PY) -m ruff format --check $(ENGINE_DIR)/src $(ENGINE_DIR)/tests scripts
	cd $(WEB_DIR) && pnpm run format:check

typecheck:
	$(ENGINE_PY) -m mypy $(ENGINE_DIR)/src
	cd $(WEB_DIR) && pnpm run typecheck

security:
	$(ENGINE_PY) -m bandit -c $(ENGINE_DIR)/pyproject.toml -r $(ENGINE_DIR)/src
	$(ENGINE_PY) -m pip_audit --skip-editable

guardrails:
	$(ENGINE_PY) scripts/guardrails.py

# --- tests ---------------------------------------------------------------

test-engine:
	cd $(ENGINE_DIR) && .venv/bin/python -m pytest tests ../scripts/tests -v

test-web:
	cd $(WEB_DIR) && pnpm run test
	cd $(WEB_DIR) && pnpm run test:e2e

test: test-engine test-web

# --- db / migrations -------------------------------------------------------

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

migrate-check:
	cd $(ENGINE_DIR) && .venv/bin/python -m alembic upgrade head

# --- build -----------------------------------------------------------------

build-web:
	cd $(WEB_DIR) && pnpm run build

# --- the gate ----------------------------------------------------------------

verify: lint format-check typecheck security guardrails migrate-check test build-web
	@echo ""
	@echo "make verify: ALL CHECKS PASSED"

clean:
	rm -rf $(ENGINE_VENV) $(WEB_DIR)/node_modules $(WEB_DIR)/.next $(ENGINE_DIR)/.pytest_cache .pytest_cache
