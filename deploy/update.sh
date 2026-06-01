#!/usr/bin/env bash
# version: 1.8.2
# description: Safe production updater for MP Control with CI/CD modes, lock, backup, and status JSON.
# updated: 2026-05-31

set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/mpcontrol}"
ENV_FILE="${ENV_FILE:-${PROJECT_DIR}/.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [[ -n "${DEPLOY_PROJECT_DIR:-}" && "${PROJECT_DIR:-}" == "/opt/mpcontrol" ]]; then
  PROJECT_DIR="$DEPLOY_PROJECT_DIR"
fi

BRANCH="${BRANCH:-main}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
SKIP_BACKUP="${SKIP_BACKUP:-0}"
SKIP_PUBLIC_HEALTH="${SKIP_PUBLIC_HEALTH:-0}"
ENABLE_TELEGRAM_DEPLOY_NOTIFICATIONS="${ENABLE_TELEGRAM_DEPLOY_NOTIFICATIONS:-true}"
DEPLOY_RUNTIME_DIR="${DEPLOY_RUNTIME_DIR:-${PROJECT_DIR}/runtime}"
LOG_FILE="${LOG_FILE:-${PROJECT_DIR}/logs/deploy/update.log}"
STATUS_FILE="${STATUS_FILE:-${DEPLOY_RUNTIME_DIR}/last_update_status.json}"
CHECK_STATUS_FILE="${CHECK_STATUS_FILE:-${DEPLOY_RUNTIME_DIR}/last_update_check.json}"
METADATA_FILE="${DEPLOY_METADATA_FILE:-${DEPLOY_RUNTIME_DIR}/deploy_metadata.json}"
TRIGGER_FILE="${DEPLOY_UPDATE_TRIGGER_FILE:-${DEPLOY_RUNTIME_DIR}/telegram_update_request.json}"
LOCK_DIR="${LOCK_DIR:-${DEPLOY_RUNTIME_DIR}/update.lock}"
APPLY_NGINX_CONFIG="${APPLY_NGINX_CONFIG:-0}"
HEALTHCHECK_RETRIES="${HEALTHCHECK_RETRIES:-60}"
HEALTHCHECK_INTERVAL_SECONDS="${HEALTHCHECK_INTERVAL_SECONDS:-2}"
PUBLIC_HEALTH_URL="${PUBLIC_HEALTH_URL:-}"
PUBLIC_HEALTH_SOURCE=""
NON_INTERACTIVE=0
CHECK_ONLY=0
VALIDATE_ENV_ONLY=0
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
)

OPTIONAL_ENV=(
  WEB_APP_BASE_URL
  API_BASE_URL
  PUBLIC_SITE_URL
)

PRODUCTION_PLACEHOLDER_URL_ENV=(
  WEB_BASE_URL
  WEB_APP_BASE_URL
  API_BASE_URL
  PUBLIC_SITE_URL
  BOT_WEBHOOK_BASE_URL
  YOOKASSA_RETURN_URL
  YOOKASSA_WEBHOOK_URL
)

PRODUCTION_PLACEHOLDER_PATH_ENV=(
  DEPLOY_PROJECT_DIR
  DEPLOY_LOG_DIR
  DEPLOY_RUNTIME_DIR
  BACKUP_DIR
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
      --validate-env-only)
        VALIDATE_ENV_ONLY=1
        ;;
      -h|--help)
        echo "Usage: bash deploy/update.sh [--non-interactive] [--check-only] [--validate-env-only]"
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
  local value=""
  if [[ -f "$ENV_FILE" ]]; then
    value="$(grep -E "^${key}=" "$ENV_FILE" | tail -n 1 | cut -d '=' -f 2- | sed 's/^"//;s/"$//;s/^'\''//;s/'\''$//' || true)"
  fi
  if [[ -z "$value" ]]; then
    value="${!key:-}"
  fi
  printf '%s' "$value"
}

url_host() {
  python3 - "$1" <<'PY'
import sys
from urllib.parse import urlparse

host = urlparse(sys.argv[1]).hostname or ""
print(host)
PY
}

is_production_env() {
  local app_env
  app_env="$(env_value "APP_ENV" | tr '[:upper:]' '[:lower:]')"
  [[ "$app_env" == "production" || "$app_env" == "prod" ]]
}

load_domains_from_env() {
  local key value host public_host
  PUBLIC_SERVER_NAMES=""
  APP_SERVER_NAMES=""
  public_host="$(url_host "$(env_value "PUBLIC_SITE_URL")")"
  if [[ -n "$public_host" ]]; then
    PUBLIC_SERVER_NAMES="${public_host} www.${public_host}"
  fi

  for key in WEB_APP_BASE_URL API_BASE_URL BOT_WEBHOOK_BASE_URL; do
    value="$(env_value "$key")"
    [[ -z "$value" ]] && continue
    host="$(url_host "$value")"
    if [[ -n "$host" && " ${APP_SERVER_NAMES} " != *" ${host} "* ]]; then
      APP_SERVER_NAMES="${APP_SERVER_NAMES:+${APP_SERVER_NAMES} }${host}"
    fi
  done
}

with_health_path() {
  local base_url="$1"
  base_url="${base_url%/}"
  if [[ "$base_url" == */health ]]; then
    printf '%s' "$base_url"
  else
    printf '%s/health' "$base_url"
  fi
}

resolve_public_health_url() {
  local base_url key
  for key in API_BASE_URL WEB_APP_BASE_URL WEB_BASE_URL PUBLIC_SITE_URL; do
    base_url="$(env_value "$key")"
    if [[ -n "$base_url" ]]; then
      PUBLIC_HEALTH_URL="$(with_health_path "$base_url")"
      PUBLIC_HEALTH_SOURCE="$key"
      return 0
    fi
  done

  log_error "Missing public healthcheck URL. Set API_BASE_URL, WEB_APP_BASE_URL, WEB_BASE_URL, or PUBLIC_SITE_URL in ${ENV_FILE}."
  exit 1
}

validate_production_placeholders() {
  if ! is_production_env; then
    return
  fi

  local key value
  for key in "${PRODUCTION_PLACEHOLDER_URL_ENV[@]}"; do
    value="$(env_value "$key")"
    if [[ "$value" == *example.com* ]]; then
      log_error "Production .env contains placeholder domain in ${key}=${value}. Replace it with real production domain, for example: ${key}=https://app.mpcontrol.online"
      exit 1
    fi
  done

  for key in "${PRODUCTION_PLACEHOLDER_PATH_ENV[@]}"; do
    value="$(env_value "$key")"
    if [[ "$value" == "/opt/example-app" || "$value" == /opt/example-app/* ]]; then
      log_error "Production .env contains placeholder path ${value} in ${key}. Replace it with /opt/mpcontrol"
      exit 1
    fi
  done
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

write_deploy_metadata() {
  cd "$PROJECT_DIR"
  local version commit commit_short branch last_commit_message updated_at
  version="$(cat VERSION 2>/dev/null || echo unknown)"
  commit="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
  commit_short="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "$BRANCH")"
  last_commit_message="$(git log -1 --format=%s 2>/dev/null || echo unknown)"
  updated_at="$(date -Is)"
  python3 - "$METADATA_FILE" "$version" "$branch" "$commit" "$commit_short" \
    "$last_commit_message" "$updated_at" <<'PY'
import json
import sys

metadata_file, version, branch, commit, commit_short, last_commit_message, updated_at = sys.argv[1:]
payload = {
    "version": version,
    "branch": branch,
    "commit": commit,
    "commit_short": commit_short,
    "last_commit_message": last_commit_message,
    "updated_at": updated_at,
}
with open(metadata_file, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
PY
  log_info "Deploy metadata written to ${METADATA_FILE}."
}

on_error() {
  local exit_code=$?
  local message="Update failed. See ${LOG_FILE} for details."
  log_error "$message"
  if [[ "$STATUS_WRITTEN" != "true" ]]; then
    write_status "failed" "$message" || true
  fi
  rm -f "$TRIGGER_FILE" || true
  notify_admins || true
  release_lock
  exit "$exit_code"
}

validate_env() {
  log_info "Validating required environment variables."
  validate_production_placeholders
  resolve_public_health_url
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
  local optional_missing=()
  for key in "${OPTIONAL_ENV[@]}"; do
    local value
    value="$(env_value "$key" || true)"
    [[ -z "$value" ]] && optional_missing+=("$key")
  done
  if [[ "${#optional_missing[@]}" -gt 0 ]]; then
    log_warn "Optional env variables are absent: ${optional_missing[*]}"
  fi
  log_info "Public API healthcheck URL resolved from ${PUBLIC_HEALTH_SOURCE}: ${PUBLIC_HEALTH_URL}"
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

finish_without_source_changes() {
  NEW_COMMIT="$OLD_COMMIT"
  NEW_VERSION="$OLD_VERSION"
  log_info "Source is already up to date; skipping backup, build, migrations, and restart."
  write_deploy_metadata
  rm -f "$TRIGGER_FILE"
  write_status "success" "No source changes detected. Update skipped safely."
  notify_admins
  print_summary
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

check_local_changes() {
  cd "$PROJECT_DIR"
  local dirty
  dirty="$(git status --porcelain --untracked-files=no)"
  if [[ -z "$dirty" ]]; then
    log_info "No local tracked changes in production worktree."
    return
  fi
  local diff_path
  diff_path="${DEPLOY_RUNTIME_DIR}/local_changes_$(date '+%Y%m%d_%H%M%S').diff"
  git diff > "$diff_path" || true
  log_error "Local tracked changes block safe update. Diff saved to ${diff_path}."
  log_error "Review server changes, commit/revert them intentionally, then re-run update."
  write_status "failed" "Local tracked changes block safe update. Diff saved to ${diff_path}."
  exit 3
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

write_service_unavailable_page() {
  mkdir -p "${PROJECT_DIR}/public"
  cat > "${PROJECT_DIR}/public/service-unavailable.html" <<'HTML'
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="5">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MP Control запускается</title>
  <style>
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f6f7f9;
      color: #111827;
    }
    .card {
      max-width: 480px;
      margin: 24px;
      padding: 32px;
      border-radius: 18px;
      background: #ffffff;
      box-shadow: 0 18px 45px rgba(17, 24, 39, 0.12);
      text-align: center;
    }
    h1 {
      margin: 0 0 12px;
      font-size: 26px;
    }
    p {
      color: #4b5563;
      line-height: 1.5;
    }
    a {
      display: inline-block;
      margin-top: 16px;
      padding: 11px 18px;
      border-radius: 10px;
      background: #2563eb;
      color: #ffffff;
      font-weight: 700;
      text-decoration: none;
    }
  </style>
</head>
<body>
  <main class="card">
    <h1>MP Control запускается</h1>
    <p>Сервис обновляется или перезапускается. Страница автоматически обновится через несколько секунд.</p>
    <p>Если вход был по ссылке из Telegram и она устарела, получите новую ссылку в боте.</p>
    <a href="https://t.me/mpcontrolrobot">Открыть бота</a>
  </main>
</body>
</html>
HTML
}

configure_nginx() {
  write_service_unavailable_page
  if [[ "$APPLY_NGINX_CONFIG" != "1" ]]; then
    log_info "Service unavailable page ensured; skipping Nginx config reload because APPLY_NGINX_CONFIG is not 1."
    return
  fi

  if [[ ! -f "${PROJECT_DIR}/deploy/nginx/mpcontrol.conf.template" ]]; then
    log_warn "Nginx template not found; skipping host Nginx reload."
    return
  fi
  if ! command -v nginx >/dev/null 2>&1; then
    log_warn "nginx command not found; skipping host Nginx reload."
    return
  fi
  if [[ ! -d /etc/nginx/sites-available ]]; then
    log_warn "/etc/nginx/sites-available is absent; skipping host Nginx reload."
    return
  fi

  load_domains_from_env
  if [[ -z "$PUBLIC_SERVER_NAMES" || -z "$APP_SERVER_NAMES" ]]; then
    log_warn "Cannot derive Nginx server names from .env; skipping host Nginx reload."
    return
  fi

  log_info "Rendering host Nginx config."
  sed "s#__PROJECT_DIR__#${PROJECT_DIR}#g" \
    "${PROJECT_DIR}/deploy/nginx/mpcontrol.conf.template" |
    sed "s#__PUBLIC_SERVER_NAMES__#${PUBLIC_SERVER_NAMES}#g" |
    sed "s#__APP_SERVER_NAMES__#${APP_SERVER_NAMES}#g" \
    > /etc/nginx/sites-available/mpcontrol.conf
  ln -sfn /etc/nginx/sites-available/mpcontrol.conf /etc/nginx/sites-enabled/mpcontrol.conf
  nginx -t
  systemctl reload nginx
  log_info "Host Nginx config reloaded."
}

ensure_alembic_version_capacity() {
  log_info "Checking alembic_version.version_num column capacity."
  local pg_user pg_db
  pg_user="$(env_value "POSTGRES_USER")"
  pg_db="$(env_value "POSTGRES_DB")"

  if [[ -z "$pg_user" || -z "$pg_db" ]]; then
    log_warn "POSTGRES_USER or POSTGRES_DB not found in .env; skipping alembic_version check."
    return 0
  fi

  local sql_check_type
  sql_check_type="
SELECT data_type, character_maximum_length
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'alembic_version'
  AND column_name = 'version_num';
"

  local sql_ensure_capacity="
DO \$\$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'alembic_version'
    ) THEN
        ALTER TABLE public.alembic_version
        ALTER COLUMN version_num TYPE VARCHAR(128);
    END IF;
END \$\$;
"

  local col_type
  col_type="$(docker compose -f "$COMPOSE_FILE" exec -T postgres \
    psql -U "$pg_user" -d "$pg_db" -t -A -c "$sql_check_type" 2>/dev/null || echo "")"

  if [[ -z "$col_type" ]]; then
    log_info "Table alembic_version does not exist yet; Alembic will create it with correct type."
    return 0
  fi

  log_info "Current alembic_version.version_num type: ${col_type}"

  docker compose -f "$COMPOSE_FILE" exec -T postgres \
    psql -U "$pg_user" -d "$pg_db" -c "$sql_ensure_capacity" || {
    log_warn "Failed to alter alembic_version.version_num; migration may fail."
    return 0
  }

  log_info "alembic_version.version_num capacity ensured: VARCHAR(128)."
}

run_migrations() {
  cd "$PROJECT_DIR"
  log_info "Starting PostgreSQL and Redis before migrations."
  docker compose -f "$COMPOSE_FILE" up -d postgres redis
  log_info "Waiting for PostgreSQL to be ready..."
  sleep 3
  ensure_alembic_version_capacity
  log_info "=== STARTING ALEMBIC MIGRATIONS ==="
  if docker compose -f "$COMPOSE_FILE" run --rm api alembic upgrade head; then
    log_info "=== ALEMBIC MIGRATIONS COMPLETED SUCCESSFULLY ==="
    MIGRATIONS_APPLIED=true
  else
    log_error "=== ALEMBIC MIGRATIONS FAILED ==="
    log_error "Deployment aborted. Fix migrations before retrying."
    log_error "Run manually: docker compose -f $COMPOSE_FILE run --rm api alembic upgrade head"
    exit 1
  fi
}

restart_services() {
  cd "$PROJECT_DIR"
  log_info "Restarting production services."
  docker compose -f "$COMPOSE_FILE" up -d
}

healthcheck() {
  wait_for_health "local API" "http://127.0.0.1:8000/health"
  if [[ "$SKIP_PUBLIC_HEALTH" != "1" ]]; then
    wait_for_health "public API" "$PUBLIC_HEALTH_URL"
  fi
  HEALTHCHECK_PASSED=true
}

wait_for_health() {
  local label="$1"
  local url="$2"
  local attempt
  log_info "Checking ${label} health: ${url}"
  for attempt in $(seq 1 "$HEALTHCHECK_RETRIES"); do
    if response="$(curl -fsS "$url" 2>/dev/null)"; then
      log_info "${label} is ready: ${response}"
      return 0
    fi
    log_warn "Healthcheck attempt ${attempt}/${HEALTHCHECK_RETRIES} failed for ${label}; waiting ${HEALTHCHECK_INTERVAL_SECONDS}s."
    sleep "$HEALTHCHECK_INTERVAL_SECONDS"
  done
  log_error "${label} healthcheck failed after ${HEALTHCHECK_RETRIES} attempts."
  return 1
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
  check_local_changes
  validate_env
  if [[ "$OLD_COMMIT" == "$REMOTE_COMMIT" ]]; then
    finish_without_source_changes
    return
  fi
  backup_database
  pull_updates
  build_images
  configure_nginx
  run_migrations
  restart_services
  healthcheck
  write_deploy_metadata
  rm -f "$TRIGGER_FILE"
  write_status "success" "Update completed successfully."
  notify_admins
  print_summary
}

parse_args "$@"

if [[ "$VALIDATE_ENV_ONLY" == "1" ]]; then
  validate_env
elif [[ "$CHECK_ONLY" == "1" ]]; then
  check_only
else
  main_update
fi
