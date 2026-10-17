#!/usr/bin/env bash
# Container start: wait for the database, migrate, then start API (or worker with ROLE=worker).
set -euo pipefail
for i in $(seq 1 60); do
  python -c "import psycopg,os;psycopg.connect(os.environ['KP_DATABASE_OWNER_URL'].replace('+psycopg','')).close()" 2>/dev/null && break
  echo "waiting for database ($i)"; sleep 2
done
if [ "${ROLE:-api}" = "worker" ]; then
  exec python -m app.jobs.worker
fi
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
