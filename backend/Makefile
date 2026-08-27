.PHONY: help install migrate seed serve test lint fmt reset check

help:
	@echo "install  - sync dependencies into .venv"
	@echo "migrate  - alembic upgrade head"
	@echo "seed     - write synthetic pilot data (refuses APP_ENV=production)"
	@echo "serve    - uvicorn with reload on :8000"
	@echo "test     - full suite (needs a reachable Postgres)"
	@echo "lint     - ruff check"
	@echo "fmt      - ruff format + import sort"
	@echo "check    - lint + test, the pre-commit gate"
	@echo "reset    - drop schema, re-migrate, re-seed (destructive)"

install:
	uv sync --extra dev

migrate:
	uv run alembic upgrade head

seed:
	uv run python -m app.seed

serve:
	uv run uvicorn app.main:app --reload --port 8000

test:
	uv run pytest -q

lint:
	uv run ruff check app tests scripts

fmt:
	uv run ruff check --select I --fix app tests scripts
	uv run ruff format app tests scripts

check: lint test

reset:
	uv run alembic downgrade base
	uv run alembic upgrade head
	uv run python -m app.seed

eval:
	uv run python -m app.eval

fetch-data:
	uv run python scripts/fetch_who_tables.py
	uv run python scripts/fetch_ifct_table.py
