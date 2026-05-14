#!/usr/bin/env bash
# version: 1.0.0
# description: Create a compressed PostgreSQL backup for MP Control production.
# updated: 2026-05-15

set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/mpcontrol}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-${PROJECT_DIR}/backups}"
LOG_FILE="${LOG_FILE:-${PROJECT_DIR}/logs/deploy/backup.log}"

mkdir -p "$(dirname "$LOG_FILE")" "$BACKUP_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: $*"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; }

env_value() {
  local key="$1"
  if [[ ! -f "${PROJECT_DIR}/.env" ]]; then
    return 0
  fi
  grep -E "^${key}=" "${PROJECT_DIR}/.env" | tail -n 1 | cut -d '=' -f 2- | sed 's/^"//;s/"$//'
}

main() {
  cd "$PROJECT_DIR"
  local db_name db_user timestamp target
  db_name="$(env_value POSTGRES_DB)"
  db_user="$(env_value POSTGRES_USER)"
  db_name="${db_name:-seller_profit_bot}"
  db_user="${db_user:-seller_bot}"
  timestamp="$(date '+%Y-%m-%d_%H-%M-%S')"
  target="${BACKUP_DIR}/mpcontrol_${timestamp}.sql.gz"

  log_info "Creating PostgreSQL backup: ${target}"
  docker compose -f "$COMPOSE_FILE" exec -T postgres pg_dump -U "$db_user" "$db_name" | gzip > "$target"
  log_info "Backup created: ${target}"
}

main "$@"
