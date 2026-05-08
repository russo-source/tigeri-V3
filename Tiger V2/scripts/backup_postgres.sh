#!/usr/bin/env bash
# Daily Postgres dump for Tigeri.
# - Runs `pg_dump` from inside the docker container so we don't need a local
#   psql client on the host.
# - Writes a compressed dump to /var/backups/tigeri/ with a date-stamped name.
# - Retains the last 7 daily dumps; older files are deleted.
# - Exits non-zero on any failure so cron emails the operator.
#
# Schedule via /etc/cron.d/tigeri-backup (see infra/aws/deploy/setup_remote.sh):
#   15 2 * * * tigeri /opt/tigeri/scripts/backup_postgres.sh
#
# Restore (on a fresh host):
#   gunzip -c /var/backups/tigeri/tigeri-YYYY-MM-DD.sql.gz | \
#     docker exec -i tigeri-postgres psql -U tigeri -d tigeri

set -euo pipefail

BACKUP_DIR="/var/backups/tigeri"
RETENTION_DAYS=7
CONTAINER="tigeri-postgres"
DB_NAME="tigeri"
DB_USER="tigeri"

mkdir -p "$BACKUP_DIR"

ts="$(date -u +%Y-%m-%dT%H%M%SZ)"
out="$BACKUP_DIR/tigeri-${ts}.sql.gz"

# pg_dump runs as the postgres superuser inside the container; -Fp gives us
# a plain-SQL dump that's easy to inspect and replay anywhere.
docker exec "$CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" \
    --no-owner --no-acl --clean --if-exists --serializable-deferrable \
    | gzip -9 > "$out"

# Sanity check — non-empty, gzip-valid file
if [ ! -s "$out" ] || ! gzip -t "$out" 2>/dev/null; then
    echo "[$(date -u +%FT%TZ)] backup FAILED: $out missing/corrupt" >&2
    rm -f "$out"
    exit 1
fi

# Prune older than RETENTION_DAYS
find "$BACKUP_DIR" -maxdepth 1 -name 'tigeri-*.sql.gz' -mtime +${RETENTION_DAYS} -delete

# Print one summary line so cron mail / journald has something to grep
size=$(stat -c '%s' "$out" 2>/dev/null || stat -f '%z' "$out")
echo "[$(date -u +%FT%TZ)] backup OK $out ($((size / 1024)) KB)"
