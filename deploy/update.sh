#!/usr/bin/env bash
# version: 1.1.0
# description: Safe production updater for MP Control with CI/CD modes, lock, backup, and status JSON.
# updated: 2026-05-15

set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/mpcontrol}"
BRANCH="${BRANCH:-main}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
SKIP_BACKUP="${SKIP_BACKUP:-0}"
SKIP_PUBLIC_HEALTH="${SKIP_PUBLIC_HEALTH:-0}"
ENABLE_TELEGRAM_DEPLOY_NOTIFICATIONS="${ENABLE_TELEGRAM_DEPLOY_NOTIFICATIONS:-true}"
DEPLOY_RUNTIME_DIR="${DEPLOY_RUNTIME_DIR:-${PROJECT_DIR}/runtime}"
LOG_FILE="${LOG_FILE:-${PROJECT_DIR}/logs/deploy/update.log}"
STATUS_FILE="${STATUS_FILE:-${DEPLOY_RUNTIME_DIR}/last_update_status.json}"
CHECK_STATUS_FILE="${CHECK_STATUS_FILE:-${DEPLOY_RUNTIME_DIR}/last_update_check.json}"
LOCK_DIR="${LOCK_DIR:-${DEPLOY_RUNTIME_DIR}/update.lock}"
NON_INTERACTIVE=0
CHECK_ONLY=0
STARTED_AT="$(date -Is)"
OLD_COMMIT=""
OLD_VERSION=""
NEW_COMMIT=""
NEW_VERSION=""
REMOTE_COMMIT=""
MIGRATIONS_APPLIED=false
BACKUP_CREATED=false
HEALTHCHECK_PASSED=false
BACKUP_METADATA_PATH=""
STATUS_WRITTEN=false
LOCK_ACQUIRED=false

REQUIRED_ENV=(
  APP_SECRET_KEY
  ENCRYPTION_KEY
  BOT_TOKEN
  ADMIN_TELEGRAM_IDS
  POSTGRES_DB
  POSTGRES_USER
  POSTGRES_PASSWORD
  DATABASE_URL
  REDIS_URL
  WEB_BASE_URL
  WEB_APP_BASE_URL
  API_BASE_URL
  PUBLIC_SITE_URL
)

mkdir -p "$(dirname "$LOG_FILE")" "$DEPLOY_RUNTIME_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: $*"; }
log_warn() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: $*"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; }

parse_args() {
  for arg in "$@"; do
    case "$arg" in
      --non-interactive)
        NON_INTERACTIVE=1
        ;;
      --check-only)
        CHECK_ONLY=1
        ;;
      -h|--help)
        echo "Usage: bash deploy/update.sh [--non-interactive] [--check-only]"
        exit 0
        ;;
      *)
        log_error "Unknown argument: ${arg}"
        exit 2
        ;;
    esac
  done
}

check_git_repo() {
  if [[ ! -d "${PROJECT_DIR}/.git" ]]; then
    log_error "${PROJECT_DIR} is not a Git repository."
    exit 1
  fi
}

acquire_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "$$" > "${LOCK_DIR}/pid"
    LOCK_ACQUIRED=true
    log_info "Update lock acquired: ${LOCK_DIR}"
    return
  fi
  local running_pid
  running_pid="$(cat "${LOCK_DIR}/pid" 2>/dev/null || echo unknown)"
  log_error "Another update is already running. Lock: ${LOCK_DIR}, pid: ${running_pid}"
  write_status "failed" "Another update is already running."
  exit 78
}

release_lock() {
  if [[ "$LOCK_ACQUIRED" == "true" && -d "$LOCK_DIR" ]]; then
    rm -rf "$LOCK_DIR"
    LOCK_ACQUIRED=false
    log_info "Update lock released."
  fi
}

env_value() {
  local key="$1"
  grep -E "^${key}=" "${PROJECT_DIR}/.env" | tail -n 1 | cut -d '=' -f 2- | sed 's/^"//;s/"$//'
}

write_json_file() {
  local target_file="$1"
  local status="$2"
  local message="$3"
  local finished_at
  finished_at="$(date -Is)"
  python3 - "$target_file" "$status" "$STARTED_AT" "$finished_at" "$OLD_COMMIT" "$NEW_COMMIT" \
    "$REMOTE_COMMIT" "$BRANCH" "$MIGRATIONS_APPLIED" "$BACKUP_CREATED" "$HEALTHCHECK_PASSED" \
    "$BACKUP_METADATA_PATH" "$message" <<'PY'
import json
import sys

(
    target_file,
    status,
    started_at,
    finished_at,
    previous_commit,
    new_commit,
    remote_commit,
    branch,
    migrations_applied,
    backup_created,
    healthcheck_passed,
    backup_metadata_path,
    message,
) = sys.argv[1:]
payload = {
    "status": status,
    "started_at": started_at,
    "finished_at": finished_at,
    "previous_commit": previous_commit or None,
    "new_commit": new_commit or None,
    "remote_commit": remote_commit or None,
    "branch": branch,
    "migrations_applied": migrations_applied == "true",
    "backup_created": backup_created == "true",
    "healthcheck_passed": healthcheck_passed == "true",
    "backup_metadata_path": backup_metadata_path or None,
    "message": message,
}
with open(target_file, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
PY
}

write_status() {
  local status="$1"
  local message="$2"
  write_json_file "$STATUS_FILE" "$status" "$message"
  STATUS_WRITTEN=true
}

notify_admins() {
  if [[ "$ENABLE_TELEGRAM_DEPLOY_NOTIFICATIONS" != "true" ]]; then
    return
  fi
  if [[ ! -f "$STATUS_FILE" ]]; then
    log_warn "Deployment status file is absent, skipping Telegram notification."
    return
  fi
  log_info "Sending Telegram deploy notification to administrators."
  docker compose -f "$COMPOSE_FILE" run --rm api \
    python -m app.cli.notify_admin_deploy --status-file "$STATUS_FILE" || \
    log_warn "Telegram deploy notification failed."
}

on_error() {
  local exit_code=$?
  local message="Update failed. See ${LOG_FILE} for details."
  log_error "$message"
  if [[ "$STATUS_WRITTEN" != "true" ]]; then
    write_status "failed" "$message" || true
  fi
  notify_admins || true
  release_lock
  exit "$exit_code"
}

validate_env() {
  log_info "Validating required environment variables."
  local missing=()
  for key in "${REQUIRED_ENV[@]}"; do
    local value
    value="$(env_value "$key" || true)"
    [[ -z "$value" ]] && missing+=("$key")
  done
  if [[ "${#missing[@]}" -gt 0 ]]; then
    log_error "Missing env variables: ${missing[*]}"
    exit 1
  fi
}

show_current_version() {
  cd "$PROJECT_DIR"
  OLD_COMMIT="$(git rev-parse HEAD)"
  OLD_VERSION="$(cat VERSION 2>/dev/null || echo unknown)"
  log_info "Current version: ${OLD_VERSION}, commit: ${OLD_COMMIT}"
}

fetch_updates() {
  cd "$PROJECT_DIR"
  log_info "Fetching updates from origin/${BRANCH}."
  git fetch origin "$BRANCH"
  REMOTE_COMMIT="$(git rev-parse "origin/${BRANCH}")"
  if [[ "$OLD_COMMIT" == "$REMOTE_COMMIT" ]]; then
    log_info "No source changes detected."
  else
    log_info "Remote update is available: ${REMOTE_COMMIT}"
  fi
}

check_only() {
  check_git_repo
  show_current_version
  fetch_updates
  local has_updates=false
  if [[ "$OLD_COMMIT" != "$REMOTE_COMMIT" ]]; then
    has_updates=true
  fi
  python3 - "$CHECK_STATUS_FILE" "$STARTED_AT" "$(date -Is)" "$OLD_COMMIT" "$REMOTE_COMMIT" "$BRANCH" "$has_updates" <<'PY'
import json
import sys

target_file, started_at, finished_at, current_commit, remote_commit, branch, has_updates = sys.argv[1:]
payload = {
    "status": "updates_available" if has_updates == "true" else "up_to_date",
    "started_at": started_at,
    "finished_at": finished_at,
    "current_commit": current_commit,
    "remote_commit": remote_commit,
    "branch": branch,
    "has_updates": has_updates == "true",
}
with open(target_file, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
PY
  if [[ "$has_updates" == "true" ]]; then
    log_info "Updates are available. Current: ${OLD_COMMIT}, remote: ${REMOTE_COMMIT}"
  else
    log_info "Installed version is up to date."
  fi
}

pull_updates() {
  cd "$PROJECT_DIR"
  git checkout "$BRANCH"
  git pull --ff-only origin "$BRANCH"
  NEW_COMMIT="$(git rev-parse HEAD)"
  NEW_VERSION="$(cat VERSION 2>/dev/null || echo unknown)"
  log_info "Updated to version: ${NEW_VERSION}, commit: ${NEW_COMMIT}"
}

check_env_diff() {
  cd "$PROJECT_DIR"
  if [[ ! -f .env || ! -f .env.example ]]; then
    log_warn "Cannot compare .env and .env.example."
    return
  fi
  local missing=()
  while IFS='=' read -r key _value; do
    [[ -z "$key" || "$key" =~ ^# ]] && continue
    if ! grep -qE "^${key}=" .env; then
      missing+=("$key")
    fi
  done < .env.example
  if [[ "${#missing[@]}" -gt 0 ]]; then
    log_warn "New variables exist in .env.example but are absent in .env: ${missing[*]}"
    log_warn "Add them manually if they are required for the new release."
  else
    log_info ".env contains all variables from .env.example."
  fi
}

backup_database() {
  if [[ "$SKIP_BACKUP" == "1" ]]; then
    log_warn "Skipping database backup because SKIP_BACKUP=1."
    BACKUP_CREATED=false
    return
  fi
  log_info "Creating backup before changing the worktree or applying migrations."
  BACKUP_METADATA_PATH="$(bash "${PROJECT_DIR}/deploy/backup.sh" | tail -n 1)"
  BACKUP_CREATED=true
  log_info "Backup completed: ${BACKUP_METADATA_PATH}"
}

build_images() {
  cd "$PROJECT_DIR"
  log_info "Building production images."
  docker compose -f "$COMPOSE_FILE" build
}

run_migrations() {
  cd "$PROJECT_DIR"
  log_info "Starting PostgreSQL and Redis before migrations."
  docker compose -f "$COMPOSE_FILE" up -d postgres redis
  log_info "Applying Alembic migrations."
  docker compose -f "$COMPOSE_FILE" run --rm api alembic upgrade head
  MIGRATIONS_APPLIED=true
}

restart_services() {
  cd "$PROJECT_DIR"
  log_info "Restarting production services."
  docker compose -f "$COMPOSE_FILE" up -d
}

healthcheck() {
  log_info "Checking local API health."
  curl -fsS http://127.0.0.1:8000/health >/dev/null
  if [[ "$SKIP_PUBLIC_HEALTH" != "1" ]]; then
    log_info "Checking public API health."
    curl -fsS https://api.mpcontrol.online/health >/dev/null
  fi
  HEALTHCHECK_PASSED=true
}

print_summary() {
  echo
  log_info "MP Control update completed."
  echo "Before: ${OLD_VERSION:-unknown} ${OLD_COMMIT:-unknown}"
  echo "After:  ${NEW_VERSION:-unknown} ${NEW_COMMIT:-unknown}"
  echo "Status: docker compose -f ${PROJECT_DIR}/${COMPOSE_FILE} ps"
}

main_update() {
  trap on_error ERR
  trap release_lock EXIT
  check_git_repo
  acquire_lock
  show_current_version
  fetch_updates
  check_env_diff
  validate_env
  backup_database
  pull_updates
  build_images
  run_migrations
  restart_services
  healthcheck
  write_status "success" "Update completed successfully."
  notify_admins
  print_summary
}

parse_args "$@"

if [[ "$CHECK_ONLY" == "1" ]]; then
  check_only
else
  main_update
fi
