#!/usr/bin/env bash
# Restore a backup created by deploy/backup.sh.
#
#   sudo ./deploy/restore.sh 2026-10-30_030000
#   sudo BACKUP_DIR=/opt/nova-backups ./deploy/restore.sh <stamp>
#
# DESTRUCTIVE: drops the current database and overwrites repos/Qdrant volumes.
# Requires typing RESTORE when prompted.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STAMP="${1:-}"
if [ -z "$STAMP" ]; then
  echo "usage: $0 <backup-stamp>" >&2
  exit 1
fi

BACKUP_DIR="${BACKUP_DIR:-$ROOT/backups}"
DB_FILE="$BACKUP_DIR/db-$STAMP.sql.gz"
REPOS_FILE="$BACKUP_DIR/repos-$STAMP.tgz"
QDRANT_FILE="$BACKUP_DIR/qdrant-$STAMP.tgz"

for file in "$DB_FILE" "$REPOS_FILE" "$QDRANT_FILE"; do
  if [ ! -f "$file" ]; then
    echo "missing backup file: $file" >&2
    exit 1
  fi
done

read_env() {
  local key="$1" fallback="$2"
  local value
  value="$(grep -E "^${key}=" .env 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
  echo "${value:-$fallback}"
}

POSTGRES_USER="$(read_env POSTGRES_USER postgres)"
POSTGRES_DB="$(read_env POSTGRES_DB nova_agent)"

volume_name() {
  local suffix="$1"
  local name
  name="$(docker volume ls -q --filter "name=${suffix}" | head -n1 || true)"
  if [ -z "$name" ]; then
    echo "volume not found: *${suffix}" >&2
    return 1
  fi
  echo "$name"
}

REPOS_VOLUME="$(volume_name repos_data)"
QDRANT_VOLUME="$(volume_name qdrant_data)"

cat <<EOF
This will restore backup '$STAMP' and OVERWRITE:
  - database $POSTGRES_DB (drop + recreate)
  - volume $REPOS_VOLUME
  - volume $QDRANT_VOLUME
EOF
read -r -p "Type RESTORE to continue: " confirmation
if [ "$confirmation" != "RESTORE" ]; then
  echo "aborted"
  exit 1
fi

echo "[1/5] stopping app and qdrant"
docker compose stop app qdrant

echo "[2/5] restoring PostgreSQL"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres \
  -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\" WITH (FORCE);" \
  -c "CREATE DATABASE \"$POSTGRES_DB\";"
gunzip -c "$DB_FILE" | docker compose exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"

echo "[3/5] restoring repos volume"
docker run --rm -v "$REPOS_VOLUME:/data" -v "$BACKUP_DIR:/backup:ro" alpine \
  sh -c 'find /data -mindepth 1 -delete && tar xzf "/backup/'"$(basename "$REPOS_FILE")"'" -C /data'

echo "[4/5] restoring qdrant volume"
docker run --rm -v "$QDRANT_VOLUME:/data" -v "$BACKUP_DIR:/backup:ro" alpine \
  sh -c 'find /data -mindepth 1 -delete && tar xzf "/backup/'"$(basename "$QDRANT_FILE")"'" -C /data'

echo "[5/5] starting services"
docker compose up -d
sleep 5
curl -fsS http://127.0.0.1:${BACKEND_PORT:-8000}/api/v1/status/health >/dev/null
echo "restore complete: $STAMP"
