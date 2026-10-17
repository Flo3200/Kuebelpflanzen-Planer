#!/usr/bin/env bash
# Restore a backup made with backup.sh.
# Usage: scripts/restore.sh backups/db_<stamp>.dump [backups/files_<stamp>.tar.gz]
# WARNING: replaces all data in the database and in the files directory.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f scripts/dev-env.sh ] && source scripts/dev-env.sh
set -a; [ -f .env ] && source .env; set +a
DUMP="${1:?Pfad zur db_*.dump angeben}"
FILES="${2:-}"
read -r -p "Alle aktuellen Daten werden ersetzt. Fortfahren? (ja/nein) " answer
[ "$answer" = "ja" ] || { echo "Abgebrochen."; exit 1; }
DB_URL="${KP_DATABASE_OWNER_URL/+psycopg/}"
pg_restore --clean --if-exists --no-owner --dbname "$DB_URL" "$DUMP"
(cd backend && uv run alembic upgrade head)
if [ -n "$FILES" ]; then
  FILES_DIR="${KP_FILES_DIR:-./data/files}"
  PARENT="$(dirname "$FILES_DIR")"
  mv "$FILES_DIR" "$FILES_DIR.before-restore-$(date +%s)" 2>/dev/null || true
  tar -xzf "$FILES" -C "$PARENT"
fi
echo "Wiederherstellung abgeschlossen."
