#!/usr/bin/env bash
# version: 1.0.0
# description: Safe production updater for MP Control installed from GitHub.
# updated: 2026-05-15

set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/mpcontrol}"
BRANCH="${BRANCH:-main}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
SKIP_BACKUP="${SKIP_BACKUP:-0}"
SKIP_PUBLIC_HEALTH="${SKIP_PUBLIC_HEALTH:-0}"
LOG_FILE="${LOG_FILE:-${PROJECT_DIR}/logs/deploy/update.log}"
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

mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: $*"; }
log_warn() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: $*"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; }

check_git_repo() {
  if [[ ! -d "${PROJECT_DIR}/.git" ]]; then
    log_error "${PROJECT_DIR} is not a Git repository."
    exit 1
  fi
}

env_value() {
  local key="$1"
  grep -E "^${key}=" "${PROJECT_DIR}/.env" | tail -n 1 | cut -d '=' -f 2- | sed 's/^"//;s/"$//'
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
  if git diff --quiet HEAD "origin/${BRANCH}"; then
    log_info "No source changes detected. Continuing with validation and healthcheck."
  else
    log_info "Changes are available and will be pulled with --ff-only."
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
    return
  fi
  log_info "Creating database backup before migrations."
  bash "${PROJECT_DIR}/deploy/backup.sh"
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
}

print_summary() {
  echo
  log_info "MP Control update completed."
  echo "Before: ${OLD_VERSION:-unknown} ${OLD_COMMIT:-unknown}"
  echo "After:  ${NEW_VERSION:-unknown} ${NEW_COMMIT:-unknown}"
  echo "Status: docker compose -f ${PROJECT_DIR}/${COMPOSE_FILE} ps"
}

main() {
  check_git_repo
  show_current_version
  fetch_updates
  pull_updates
  check_env_diff
  validate_env
  backup_database
  build_images
  run_migrations
  restart_services
  healthcheck
  print_summary
}

main "$@"
