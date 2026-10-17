#!/usr/bin/env bash
# Daily backup: database dump (pg_dump, custom format) + archive of data/files.
# Usage: scripts/backup.sh [target-dir]     (default: ./backups)
# Keeps the last KEEP_DAYS backups (default 14). Suitable for cron/launchd:
#   0 3 * * *  /path/to/Kuebelpflanzen-Planer/scripts/backup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f scripts/dev-env.sh ] && source scripts/dev-env.sh
set -a; [ -f .env ] && source .env; set +a
TARGET="${1:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%Y-%m-%d_%H%M%S)"
mkdir -p "$TARGET"
DB_URL="${KP_DATABASE_OWNER_URL/+psycopg/}"
FILES_DIR="${KP_FILES_DIR:-./data/files}"
pg_dump --format=custom --no-owner --file "$TARGET/db_$STAMP.dump" "$DB_URL"
tar -czf "$TARGET/files_$STAMP.tar.gz" -C "$(dirname "$FILES_DIR")" "$(basename "$FILES_DIR")"
find "$TARGET" -name 'db_*.dump' -mtime +"$KEEP_DAYS" -delete
find "$TARGET" -name 'files_*.tar.gz' -mtime +"$KEEP_DAYS" -delete
echo "Sicherung erstellt: $TARGET/db_$STAMP.dump und $TARGET/files_$STAMP.tar.gz"
