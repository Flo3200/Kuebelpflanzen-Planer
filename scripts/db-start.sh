#!/usr/bin/env bash
# Starts the local PostgreSQL cluster in data/postgres (development without Docker).
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/dev-env.sh
if pg_ctl -D data/postgres status >/dev/null 2>&1; then
  echo "PostgreSQL läuft bereits."
else
  pg_ctl -D data/postgres -l data/postgres.log start
fi
