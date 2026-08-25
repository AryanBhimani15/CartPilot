SHELL := /bin/sh

API_DIR := api
WEB_DIR := web
PY := cd $(API_DIR) && uv run

.DEFAULT_GOAL := dev

.PHONY: setup db seed dev dev-api dev-web test types eval lint typecheck

setup:
	@test -f .env || cp .env.example .env
	uv sync --project $(API_DIR) --extra dev
	npm --prefix $(WEB_DIR) install
	@echo "Setup complete. Review .env before using real services."

db:
	@set -a; . ./.env; set +a; \
	DB_NAME=$$(python3 -c "from urllib.parse import urlparse; import os; print(urlparse(os.environ['DATABASE_URL'].replace('+asyncpg', '')).path.lstrip('/'))"); \
	psql -d postgres -tc "SELECT 1 FROM pg_database WHERE datname = '$$DB_NAME'" | grep -q 1 || psql -d postgres -c "CREATE DATABASE \"$$DB_NAME\""; \
	$(PY) alembic -c alembic.ini upgrade head

seed: db
	@set -a; . ./.env; set +a; $(PY) python -m app.db.seed.catalog

dev:
	@trap 'kill 0' INT TERM EXIT; $(MAKE) dev-api & $(MAKE) dev-web & wait

dev-api:
	@set -a; . ./.env; set +a; $(PY) uvicorn app.main:app --host 127.0.0.1 --port $${API_PORT:-8000} --reload

dev-web:
	npm --prefix $(WEB_DIR) run dev

test:
	@set -a; . ./.env; set +a; \
	(cd $(API_DIR) && \
	APP_ENV=test TEST_DATABASE_URL=$${TEST_DATABASE_URL:-postgresql+asyncpg:///cartpilot_test} \
	uv run pytest tests)

types:
	@set -a; . ./.env; set +a; $(PY) python -m scripts.generate_openapi_types
	npm --prefix $(WEB_DIR) exec -- openapi-typescript $(WEB_DIR)/types/openapi.json -o $(WEB_DIR)/types/api.ts

typecheck:
	$(PY) mypy --strict app
	npm --prefix $(WEB_DIR) run typecheck

eval:
	@echo "Evaluation is introduced in T-012."

lint:
	$(PY) ruff check .
	npm --prefix $(WEB_DIR) run lint
