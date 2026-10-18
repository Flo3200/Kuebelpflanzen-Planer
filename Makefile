# One command for everything: `make check` (lint + typecheck + all tests)
SHELL := /bin/bash
ENV := source scripts/dev-env.sh &&

.PHONY: dev db test test-backend test-frontend lint format check build demo backup agent-readme

dev:            ## API + worker + built frontend on http://localhost:8000
	bash scripts/dev.sh

db:             ## start local PostgreSQL
	bash scripts/db-start.sh

build:          ## build the frontend into frontend/dist
	$(ENV) cd frontend && npm run build

demo:           ## load demo data (replaces existing demo tenants)
	$(ENV) cd backend && uv run python -m app.demo --reset

test-backend:
	$(ENV) cd backend && PYTHONPATH=. uv run pytest -q

test-frontend:
	$(ENV) cd frontend && npm run typecheck && npm test

test: test-backend test-frontend

lint:
	$(ENV) cd backend && uv run ruff check app tests && uv run ruff format --check app tests
	$(ENV) cd frontend && npm run lint

format:
	$(ENV) cd backend && uv run ruff check --fix app tests && uv run ruff format app tests
	$(ENV) cd frontend && npm run format

check: lint test

backup:
	bash scripts/backup.sh

agent-readme:   ## write agent/README.md from the API (also served live at /agent/README.md)
	$(ENV) cd backend && PYTHONPATH=. uv run python tools/agent_readme.py ../agent/README.md
