#!/usr/bin/env bash
# version: 1.8.1
# description: Create PostgreSQL, .env, and metadata backups for MP Control production.
# updated: 2026-05-15

set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/mpcontrol}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-${PROJECT_DIR}/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
LOG_FILE="${LOG_FILE:-${PROJECT_DIR}/logs/deploy/backup.log}"

mkdir -p "$(dirname "$LOG_FILE")" "$BACKUP_DIR/db" "$BACKUP_DIR/env" "$BACKUP_DIR/meta"
exec > >(tee -a "$LOG_FILE") 2>&1

log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: $*"; }
log_warn() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: $*"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; }

env_value() {
  local key="$1"
  if [[ ! -f "${PROJECT_DIR}/.env" ]]; then
    return 0
  fi
  grep -E "^${key}=" "${PROJECT_DIR}/.env" | tail -n 1 | cut -d '=' -f 2- | sed 's/^"//;s/"$//'
}

cleanup_old_backups() {
  if [[ "$BACKUP_RETENTION_DAYS" =~ ^[0-9]+$ ]] && [[ "$BACKUP_RETENTION_DAYS" -gt 0 ]]; then
    log_info "Removing backups older than ${BACKUP_RETENTION_DAYS} days."
    find "$BACKUP_DIR/db" -type f -mtime +"$BACKUP_RETENTION_DAYS" -delete || true
    find "$BACKUP_DIR/env" -type f -mtime +"$BACKUP_RETENTION_DAYS" -delete || true
    find "$BACKUP_DIR/meta" -type f -mtime +"$BACKUP_RETENTION_DAYS" -delete || true
  else
    log_warn "BACKUP_RETENTION_DAYS is invalid, skipping retention cleanup."
  fi
}

write_metadata() {
  local metadata_path="$1"
  local timestamp="$2"
  local db_backup_path="$3"
  local env_backup_path="$4"
  local commit branch version
  commit="$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
  branch="$(git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
  version="$(cat "${PROJECT_DIR}/VERSION" 2>/dev/null || echo unknown)"

  python3 - "$metadata_path" "$timestamp" "$commit" "$branch" "$version" "$db_backup_path" "$env_backup_path" <<'PY'
import json
import sys

metadata_path, timestamp, commit, branch, version, db_backup_path, env_backup_path = sys.argv[1:]
payload = {
    "created_at": timestamp,
    "git_commit": commit,
    "git_branch": branch,
    "app_version": version,
    "db_backup_path": db_backup_path,
    "env_backup_path": env_backup_path,
}
with open(metadata_path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
PY
}

main() {
  cd "$PROJECT_DIR"
  local db_name db_user timestamp db_target env_target metadata_target
  db_name="$(env_value POSTGRES_DB)"
  db_user="$(env_value POSTGRES_USER)"
  db_name="${db_name:-seller_profit_bot}"
  db_user="${db_user:-seller_bot}"
  timestamp="$(date '+%Y-%m-%d_%H-%M-%S')"
  db_target="${BACKUP_DIR}/db/mpcontrol_${timestamp}.sql.gz"
  env_target="${BACKUP_DIR}/env/.env_${timestamp}.backup"
  metadata_target="${BACKUP_DIR}/meta/backup_${timestamp}.json"

  log_info "Creating PostgreSQL backup: ${db_target}"
  docker compose -f "$COMPOSE_FILE" exec -T postgres pg_dump -U "$db_user" "$db_name" | gzip > "$db_target"

  if [[ -f "${PROJECT_DIR}/.env" ]]; then
    log_info "Copying .env backup: ${env_target}"
    cp "${PROJECT_DIR}/.env" "$env_target"
    chmod 600 "$env_target"
  else
    log_warn ".env not found, env backup will be marked as absent."
    env_target=""
  fi

  write_metadata "$metadata_target" "$(date -Is)" "$db_target" "$env_target"
  cleanup_old_backups

  log_info "Backup metadata created: ${metadata_target}"
  echo "$metadata_target"
}

main "$@"
