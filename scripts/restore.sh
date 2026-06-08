#!/usr/bin/env bash
# version: 1.0.0
# description: Restore MP Control PostgreSQL dump and optional config files from a backup archive.
# updated: 2026-06-07

set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/mpcontrol}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-${PROJECT_DIR}/.env}"
RESTORE_CONFIRM="${RESTORE_CONFIRM:-}"
RESTORE_FILES="${RESTORE_FILES:-0}"
BACKUP_PATH="${1:-}"
WORK_DIR=""

log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: $*"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; }

cleanup() {
  if [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]]; then
    rm -rf "$WORK_DIR"
  fi
}
trap cleanup EXIT

env_value() {
  local key="$1"
  if [[ ! -f "$ENV_FILE" ]]; then
    return 0
  fi
  grep -E "^${key}=" "$ENV_FILE" | tail -n 1 | cut -d '=' -f 2- | sed 's/^"//;s/"$//;s/^'\''//;s/'\''$//'
}

require_file() {
  if [[ -z "$BACKUP_PATH" ]]; then
    log_error "Usage: RESTORE_CONFIRM=YES $0 /opt/mpcontrol/backups/daily/mpcontrol_full_YYYY-MM-DD_HH-MM-SS.tar.gz"
    exit 1
  fi
  if [[ ! -f "$BACKUP_PATH" ]]; then
    log_error "Backup archive not found: ${BACKUP_PATH}"
    exit 1
  fi
}

require_confirmation() {
  if [[ "$RESTORE_CONFIRM" != "YES" ]]; then
    log_error "Refusing to restore without explicit confirmation."
    log_error "Run: RESTORE_CONFIRM=YES $0 ${BACKUP_PATH}"
    exit 1
  fi
}

find_first() {
  local pattern="$1"
  find "$WORK_DIR" -type f -name "$pattern" | head -n 1
}

decrypt_if_needed() {
  local path="$1"
  if [[ "$path" != *.gpg ]]; then
    echo "$path"
    return 0
  fi

  local password output
  password="${BACKUP_ENCRYPTION_PASSWORD:-$(env_value BACKUP_ENCRYPTION_PASSWORD)}"
  if [[ -z "$password" ]]; then
    log_error "Encrypted backup found, but BACKUP_ENCRYPTION_PASSWORD is empty."
    exit 1
  fi
  if ! command -v gpg >/dev/null 2>&1; then
    log_error "Encrypted backup found, but gpg is not installed."
    exit 1
  fi
  output="${path%.gpg}"
  gpg --batch --yes --decrypt --passphrase "$password" --output "$output" "$path" >/dev/null
  chmod 600 "$output"
  echo "$output"
}

main() {
  require_file
  require_confirmation
  cd "$PROJECT_DIR"

  WORK_DIR="$(mktemp -d)"
  log_info "Extracting backup archive to ${WORK_DIR}."
  tar -xzf "$BACKUP_PATH" -C "$WORK_DIR"

  local db_dump files_archive pg_user pg_db safety_name
  db_dump="$(find_first '*.sql.gz')"
  if [[ -z "$db_dump" ]]; then
    db_dump="$(find_first '*.sql.gz.gpg')"
  fi
  files_archive="$(find_first 'mpcontrol_files_*.tar.gz')"
  if [[ -z "$files_archive" ]]; then
    files_archive="$(find_first 'mpcontrol_files_*.tar.gz.gpg')"
  fi
  pg_user="$(env_value POSTGRES_USER)"
  pg_db="$(env_value POSTGRES_DB)"
  pg_user="${pg_user:-seller_bot}"
  pg_db="${pg_db:-seller_profit_bot}"

  if [[ -z "$db_dump" ]]; then
    log_error "No PostgreSQL .sql.gz dump found inside backup archive."
    exit 1
  fi
  db_dump="$(decrypt_if_needed "$db_dump")"
  if [[ -n "$files_archive" ]]; then
    files_archive="$(decrypt_if_needed "$files_archive")"
  fi

  log_info "Creating safety backup before restore."
  safety_name="${PROJECT_DIR}/backups/restore/safety_before_restore_$(date '+%Y-%m-%d_%H-%M-%S').sql.gz"
  mkdir -p "$(dirname "$safety_name")"
  docker compose -f "$COMPOSE_FILE" exec -T postgres pg_dump \
    -U "$pg_user" -d "$pg_db" --format=plain --no-owner --no-privileges | gzip > "$safety_name"
  chmod 600 "$safety_name"

  log_info "Restoring PostgreSQL database ${pg_db} from $(basename "$db_dump")."
  docker compose -f "$COMPOSE_FILE" exec -T postgres psql -U "$pg_user" -d postgres \
    -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${pg_db}' AND pid <> pg_backend_pid();" >/dev/null
  docker compose -f "$COMPOSE_FILE" exec -T postgres dropdb -U "$pg_user" --if-exists "$pg_db"
  docker compose -f "$COMPOSE_FILE" exec -T postgres createdb -U "$pg_user" "$pg_db"
  gunzip -c "$db_dump" | docker compose -f "$COMPOSE_FILE" exec -T postgres psql -U "$pg_user" -d "$pg_db"

  if [[ "$RESTORE_FILES" == "1" ]]; then
    if [[ -z "$files_archive" ]]; then
      log_error "RESTORE_FILES=1 was set, but no files archive was found."
      exit 1
    fi
    log_info "Restoring config/runtime files from $(basename "$files_archive")."
    tar -xzf "$files_archive" -C "$PROJECT_DIR"
    [[ -f "${PROJECT_DIR}/.env" ]] && chmod 600 "${PROJECT_DIR}/.env"
  else
    log_info "Config/runtime files were not restored. Set RESTORE_FILES=1 to restore them."
  fi

  log_info "Restore completed. Restart services with: docker compose -f ${COMPOSE_FILE} up -d"
}

main "$@"
