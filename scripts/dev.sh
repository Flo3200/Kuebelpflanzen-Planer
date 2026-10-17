#!/usr/bin/env bash
# Development start without Docker: database, migrations, API server with embedded worker.
# The built frontend (frontend/dist) is served under the same address: http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/dev-env.sh
bash scripts/db-start.sh
cd backend
uv run alembic upgrade head
KP_EMBEDDED_WORKER=true exec uv run uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}" "$@"
