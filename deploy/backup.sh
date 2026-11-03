#!/usr/bin/env bash
# Nightly-ish backup for a docker-compose deployment.
#
#   sudo BACKUP_DIR=/opt/nova-backups ./deploy/backup.sh
#
# Dumps PostgreSQL, snapshots Qdrant (falls back to a volume tar), and archives
# the repos volume. Keeps RETENTION_DAYS of backups.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BACKUP_DIR="${BACKUP_DIR:-$ROOT/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
STAMP="$(date +%F_%H%M%S)"
mkdir -p "$BACKUP_DIR"

read_env() {
  local key="$1" fallback="$2"
  local value
  value="$(grep -E "^${key}=" .env 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
  echo "${value:-$fallback}"
}

POSTGRES_USER="$(read_env POSTGRES_USER postgres)"
POSTGRES_DB="$(read_env POSTGRES_DB nova_agent)"
QDRANT_COLLECTION="$(read_env QDRANT_COLLECTION code_chunks)"

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

# 管道里任何一段失败都要让整个脚本失败。默认 set -e 只看管道最后一个命令，
# pg_dump 挂了 gzip 仍会「成功」，产出一个空文件，等真出事才发现。
set -o pipefail

echo "[1/3] PostgreSQL dump"
DB_FILE="$BACKUP_DIR/db-$STAMP.sql.gz"
docker compose exec -T postgres \
  pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
  | gzip > "$DB_FILE"

# 空 dump 或解压失败都算备份失败：宁可这次报错，也不要留下一个看似正常的空备份。
if ! gzip -t "$DB_FILE" 2>/dev/null; then
  echo "backup failed: $DB_FILE is not a valid gzip stream" >&2
  rm -f "$DB_FILE"
  exit 1
fi
if ! [ -s "$DB_FILE" ]; then
  echo "backup failed: $DB_FILE is empty" >&2
  rm -f "$DB_FILE"
  exit 1
fi

echo "[2/3] Qdrant snapshot"
QDRANT_CID="$(docker compose ps -q qdrant)"
SNAPSHOT_JSON=""
if docker compose exec -T qdrant sh -c 'command -v curl >/dev/null 2>&1'; then
  SNAPSHOT_JSON="$(docker compose exec -T qdrant sh -c \
    "curl -fsS -X POST http://localhost:6333/collections/${QDRANT_COLLECTION}/snapshots" || true)"
fi
SNAPSHOT_NAME="$(printf '%s' "$SNAPSHOT_JSON" | sed -n 's/.*"name":"\([^"]*\)".*/\1/p')"
if [ -n "$SNAPSHOT_NAME" ]; then
  docker cp "$QDRANT_CID:/qdrant/snapshots/$SNAPSHOT_NAME" \
    "$BACKUP_DIR/qdrant-$STAMP.snapshot"
  echo "  snapshot: $SNAPSHOT_NAME"
else
  echo "  snapshot API unavailable"
fi
# Always keep a volume tar as the simple restore path.
QDRANT_VOLUME="$(volume_name qdrant_data)"
docker run --rm -v "$QDRANT_VOLUME:/data:ro" -v "$BACKUP_DIR:/backup" alpine \
  tar czf "/backup/qdrant-$STAMP.tgz" -C /data .

echo "[3/3] Repos volume"
REPOS_VOLUME="$(volume_name repos_data)"
docker run --rm -v "$REPOS_VOLUME:/data:ro" -v "$BACKUP_DIR:/backup" alpine \
  tar czf "/backup/repos-$STAMP.tgz" -C /data .

echo "Pruning files older than ${RETENTION_DAYS} days"
find "$BACKUP_DIR" -maxdepth 1 -type f -mtime "+${RETENTION_DAYS}" -delete

echo "Backup complete: $BACKUP_DIR (stamp $STAMP)"
