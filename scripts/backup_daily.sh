#!/usr/bin/env bash
# Daily PostgreSQL and important files backup for MP Control production.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${PARENT_DIR}/.env"

# ── Safe .env loader ──────────────────────────────────────────────────
# Reads KEY=value lines, ignores comments/empties, handles quoted values
load_env_file() {
  local file="$1" line key val
  [[ ! -f "$file" ]] && return 1
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$line" ]] && continue
    [[ "$line" =~ ^# ]] && continue
    if [[ "$line" =~ ^([a-zA-Z_][a-zA-Z0-9_]*)=(.*)$ ]]; then
      key="${BASH_REMATCH[1]}"
      val="${BASH_REMATCH[2]}"
      if [[ "$val" =~ ^\"(.*)\"$ ]]; then
        val="${BASH_REMATCH[1]}"
      elif [[ "$val" =~ ^\'(.*)\'$ ]]; then
        val="${BASH_REMATCH[1]}"
      fi
      printf -v "$key" "%s" "$val"
      export "$key"
    fi
  done < "$file"
}

load_env_file "$ENV_FILE" || echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: .env not found: ${ENV_FILE}"

# ── Paths ──────────────────────────────────────────────────────────────
PROJECT_DIR="${DEPLOY_PROJECT_DIR:-$PARENT_DIR}"
COMPOSE_FILE="${COMPOSE_FILE:-${PROJECT_DIR}/docker-compose.prod.yml}"
BACKUP_ROOT="${BACKUP_DIR:-${PROJECT_DIR}/backups}"

BACKUP_DAILY_DIR="${BACKUP_ROOT}/daily"
BACKUP_WEEKLY_DIR="${BACKUP_ROOT}/weekly"
BACKUP_MONTHLY_DIR="${BACKUP_ROOT}/monthly"
BACKUP_ARCHIVE_DIR="${BACKUP_ROOT}/archive"
BACKUP_LOG_DIR="${BACKUP_ROOT}/logs"
BACKUP_TMP_DIR="${BACKUP_ROOT}/tmp"

LOG_FILE="${BACKUP_LOG_DIR}/backup_$(date '+%Y-%m-%d').log"
TIMESTAMP="$(date '+%Y-%m-%d_%H-%M-%S')"

mkdir -p "$BACKUP_DAILY_DIR" "$BACKUP_WEEKLY_DIR" "$BACKUP_MONTHLY_DIR" \
        "$BACKUP_ARCHIVE_DIR" "$BACKUP_LOG_DIR" "$BACKUP_TMP_DIR"
chmod 700 "$BACKUP_ROOT"

# Log to both stdout (for journald) and log file
exec > >(tee -a "$LOG_FILE") 2>&1

# ── Helper functions ──────────────────────────────────────────────────
log_info()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: $*"; }
log_warn()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: $*"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; }

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "$2" "Command $1 not found"
  fi
}

human_size() {
  local path="$1" bytes
  if command -v stat >/dev/null 2>&1; then
    bytes="$(stat -c%s "$path" 2>/dev/null || stat -f%z "$path" 2>/dev/null || echo 0)"
  else
    bytes=0
  fi
  if command -v numfmt >/dev/null 2>&1; then
    numfmt --to=iec --suffix=B --format="%.1f" "$bytes"
  else
    echo "$bytes bytes"
  fi
}

file_size() {
  stat -c%s "$1" 2>/dev/null || stat -f%z "$1" 2>/dev/null || echo 0
}

duration() {
  local seconds=$1
  printf "%dm%ds" $((seconds / 60)) $((seconds % 60))
}

# ── Trap / cleanup ────────────────────────────────────────────────────
CLEANUP_FILES=()

cleanup() {
  local exit_code=$?
  if [[ ${#CLEANUP_FILES[@]} -gt 0 ]]; then
    for f in "${CLEANUP_FILES[@]}"; do
      [[ -f "$f" ]] && rm -f "$f"
    done
  fi
  if [[ -d "$BACKUP_TMP_DIR" && "$BACKUP_TMP_DIR" == */backups/tmp ]]; then
    rm -f "$BACKUP_TMP_DIR"/*.tmp "$BACKUP_TMP_DIR"/*.tmp.enc 2>/dev/null || true
  fi
  if [[ $exit_code -ne 0 ]]; then
    log_error "Backup failed with exit code ${exit_code}"
  fi
  exit "$exit_code"
}
trap cleanup EXIT

fail() {
  local stage="$1" message="$2"
  log_error "${stage}: ${message}"
  notify_telegram "BACKUP FAILED
Server: $(hostname -s 2>/dev/null || echo unknown)
Date: $(date '+%d.%m.%Y %H:%M')
Stage: ${stage}
Error: ${message}

Check server and logs."
  exit 1
}

# ── Telegram notification with retry on 429 ──────────────────────────
notify_telegram() {
  local text="$1"
  if [[ "${BACKUP_TELEGRAM_NOTIFY:-1}" != "1" ]]; then
    return 0
  fi
  if [[ -z "${BOT_TOKEN:-}" || -z "${ADMIN_TELEGRAM_IDS:-}" ]]; then
    log_warn "Telegram notification skipped: BOT_TOKEN or ADMIN_TELEGRAM_IDS not set"
    return 0
  fi
  local admin_id attempt
  IFS=',' read -ra admins <<< "$ADMIN_TELEGRAM_IDS"
  for admin_id in "${admins[@]}"; do
    admin_id="$(echo "$admin_id" | xargs)"
    [[ -z "$admin_id" ]] && continue
    for attempt in 1 2 3; do
      local http_code response
      response="$(curl -fsS -o /dev/null -w "%{http_code}" \
        -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d "chat_id=${admin_id}" \
        --data-urlencode "text=${text}" \
        2>/dev/null || echo "curl_failed")"
      http_code="$response"
      if [[ "$http_code" == "200" ]]; then
        break
      fi
      if [[ "$http_code" == "429" ]]; then
        local retry_after
        retry_after="$(curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
          -d "chat_id=${admin_id}" \
          --data-urlencode "text=${text}" \
          2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('parameters',{}).get('retry_after',5))" 2>/dev/null || echo 5)"
        log_warn "Telegram 429 (rate limit), retrying in ${retry_after}s (attempt ${attempt}/3)"
        sleep "$retry_after"
      elif [[ "$http_code" =~ ^(5[0-9][0-9])$ ]]; then
        log_warn "Telegram 5xx (attempt ${attempt}/3), retrying in ${attempt}s"
        sleep "$attempt"
      else
        log_warn "Telegram HTTP ${http_code} for admin ${admin_id} (attempt ${attempt}/3)"
        break
      fi
    done
  done
}

# ── Archive security ──────────────────────────────────────────────────
check_archive_security() {
  if [[ "${BACKUP_INCLUDE_FILES:-1}" != "1" ]]; then
    return 0
  fi
  local is_prod=false
  if [[ "${APP_ENV:-local}" =~ ^(production|prod|staging)$ ]]; then
    is_prod=true
  fi

  if $is_prod && [[ "${BACKUP_ENCRYPTION_ENABLED:-0}" != "1" ]] \
     && [[ "${BACKUP_ALLOW_PLAINTEXT_SECRETS:-0}" != "1" ]]; then
    log_error "Production environment: file archive may contain .env with secrets."
    log_error "Either set BACKUP_ENCRYPTION_ENABLED=1 with a strong BACKUP_ENCRYPTION_PASSWORD,"
    log_error "or explicitly set BACKUP_ALLOW_PLAINTEXT_SECRETS=1 to allow plaintext secrets."
    fail "Security check" "Production requires encryption or explicit plaintext opt-in"
  fi

  if [[ "${BACKUP_ENCRYPTION_ENABLED:-0}" == "1" && -z "${BACKUP_ENCRYPTION_PASSWORD:-}" ]]; then
    fail "Security check" "BACKUP_ENCRYPTION_ENABLED=1 but BACKUP_ENCRYPTION_PASSWORD is empty"
  fi
}

# ── Encryption ─────────────────────────────────────────────────────────
encrypt_if_enabled() {
  local path="$1"
  if [[ "${BACKUP_ENCRYPTION_ENABLED:-0}" != "1" ]]; then
    echo "$path"
    return 0
  fi
  if [[ -z "${BACKUP_ENCRYPTION_PASSWORD:-}" ]]; then
    fail "Encryption" "BACKUP_ENCRYPTION_ENABLED=1 but BACKUP_ENCRYPTION_PASSWORD is empty"
  fi
  local encrypted="${path}.enc"
  if command -v openssl >/dev/null 2>&1; then
    openssl enc -aes-256-cbc -pbkdf2 -salt \
      -in "$path" \
      -out "$encrypted" \
      -pass "pass:${BACKUP_ENCRYPTION_PASSWORD}" 2>/dev/null
    chmod 600 "$encrypted"
    rm -f "$path"
    echo "$encrypted"
  elif command -v gpg >/dev/null 2>&1; then
    gpg --batch --yes --symmetric --cipher-algo AES256 \
      --passphrase "$BACKUP_ENCRYPTION_PASSWORD" \
      --output "${encrypted}" "$path"
    chmod 600 "$encrypted"
    rm -f "$path"
    echo "$encrypted"
  else
    fail "Encryption" "openssl or gpg not found. Install openssl: apt install openssl"
  fi
}

# ── File validation ────────────────────────────────────────────────────
validate_file() {
  local path="$1" stage="$2"
  if [[ ! -f "$path" ]]; then
    fail "$stage" "file not found: ${path}"
  fi
  if [[ ! -s "$path" ]]; then
    fail "$stage" "file is empty: ${path}"
  fi
  local size
  size="$(file_size "$path")"
  if [[ "$size" -le 1024 ]]; then
    fail "$stage" "file suspiciously small (${size} bytes): ${path}"
  fi
}

# ── Retention ──────────────────────────────────────────────────────────
cleanup_retention() {
  local dir="$1" days="$2" label="$3"
  if [[ ! -d "$dir" ]]; then
    return
  fi
  if [[ ! "$days" =~ ^[0-9]+$ ]] || [[ "$days" -le 0 ]]; then
    log_warn "Retention ${label}: invalid days=${days}, skipping"
    return
  fi
  if [[ ! "$dir" == "${BACKUP_ROOT}"/* ]]; then
    log_warn "Retention ${label}: directory ${dir} is outside backup root, skipping"
    return
  fi
  local count_before count_after
  count_before="$(find "$dir" -type f | wc -l)"
  find "$dir" -type f -mtime +"$days" -delete 2>/dev/null || true
  count_after="$(find "$dir" -type f | wc -l)"
  local deleted=$((count_before - count_after))
  if [[ $deleted -gt 0 ]]; then
    log_info "Retention ${label}: removed ${deleted} file(s) older than ${days} days from ${dir}"
  fi
}

# ── Archive project files ──────────────────────────────────────────────
archive_project_files() {
  local target="$1"
  local exclude_env=()
  if [[ "${BACKUP_ENCRYPTION_ENABLED:-0}" != "1" && "${BACKUP_ALLOW_PLAINTEXT_SECRETS:-0}" != "1" ]]; then
    exclude_env=("--exclude=.env")
  fi
  if ! tar \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='venv' \
    --exclude='env' \
    --exclude='node_modules' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='.mypy_cache' \
    --exclude='.ruff_cache' \
    --exclude='logs' \
    --exclude='backups' \
    --exclude='tmp' \
    --exclude='*.tmp' \
    --exclude='*.pyc' \
    --exclude='postgres_data' \
    --exclude='redis_data' \
    "${exclude_env[@]}" \
    -czf "$target" \
    -C "$PROJECT_DIR" \
    .env docker-compose.prod.yml deploy nginx uploads storage runtime 2>&1; then
    rm -f "$target"
    fail "Archive project files" "tar failed"
  fi
}

# ── Determine backup type ──────────────────────────────────────────────
get_backup_type() {
  local day_of_week month_of_year
  day_of_week="$(date '+%u')"
  month_of_year="$(date '+%d')"
  if [[ "$day_of_week" == "7" ]]; then
    echo "weekly"
  elif [[ "$month_of_year" == "01" ]]; then
    echo "monthly"
  else
    echo "daily"
  fi
}

# ── Main ───────────────────────────────────────────────────────────────
main() {
  if [[ "${BACKUP_ENABLED:-1}" != "1" ]]; then
    log_info "Backups disabled: BACKUP_ENABLED=${BACKUP_ENABLED:-0}"
    exit 0
  fi

  local START_SEC
  START_SEC="$(date '+%s')"

  check_archive_security

  cd "$PROJECT_DIR"
  require_command docker "Docker check"
  require_command gzip "gzip check"
  require_command tar "tar check"
  if [[ "${BACKUP_TELEGRAM_NOTIFY:-1}" == "1" ]]; then
    require_command curl "Telegram notification"
  fi

  local compose_cmd=(docker compose -f "$COMPOSE_FILE")
  if ! "${compose_cmd[@]}" ps postgres >/dev/null 2>&1; then
    fail "PostgreSQL check" "postgres container not found"
  fi

  local backup_type db_backup_tmp db_backup_final \
        files_backup_tmp files_backup_final

  backup_type="$(get_backup_type)"

  log_info "Starting ${backup_type} backup of MP Control"
  log_info "Backup root: ${BACKUP_ROOT}"

  # ── 1. PostgreSQL dump ─────────────────────────────────────────────
  db_backup_tmp="${BACKUP_TMP_DIR}/mpcontrol_db_${TIMESTAMP}.sql.gz.tmp"
  db_backup_final="${BACKUP_DAILY_DIR}/mpcontrol_db_${TIMESTAMP}.sql.gz"
  CLEANUP_FILES+=("$db_backup_tmp")

  log_info "Creating PostgreSQL dump: ${db_backup_final}"

  local pg_user pg_db pg_exit gzip_exit
  pg_user="${POSTGRES_USER:-seller_bot}"
  pg_db="${POSTGRES_DB:-seller_profit_bot}"

  # Use PG* environment variables for direct connection if DATABASE_URL is set,
  # otherwise use docker-compose exec
  set +e
  "${compose_cmd[@]}" exec -T postgres pg_dump \
    -U "$pg_user" \
    -d "$pg_db" \
    --format=plain \
    --no-owner \
    --no-privileges \
    2>"${BACKUP_TMP_DIR}/pg_dump_${TIMESTAMP}.stderr" \
    | gzip > "$db_backup_tmp"
  pg_exit="${PIPESTATUS[0]}"
  gzip_exit="${PIPESTATUS[1]}"
  set -e

  if [[ "$pg_exit" -ne 0 ]]; then
    if [[ -f "${BACKUP_TMP_DIR}/pg_dump_${TIMESTAMP}.stderr" ]]; then
      log_error "pg_dump stderr:"
      cat "${BACKUP_TMP_DIR}/pg_dump_${TIMESTAMP}.stderr" >&2
    fi
    rm -f "$db_backup_tmp"
    fail "PostgreSQL dump" "pg_dump failed with exit code ${pg_exit}"
  fi
  if [[ "$gzip_exit" -ne 0 ]]; then
    rm -f "$db_backup_tmp"
    fail "PostgreSQL dump" "gzip failed with exit code ${gzip_exit}"
  fi
  rm -f "${BACKUP_TMP_DIR}/pg_dump_${TIMESTAMP}.stderr"

  validate_file "$db_backup_tmp" "PostgreSQL dump"

  # Verify: gzip integrity
  if ! gzip -t "$db_backup_tmp" 2>/dev/null; then
    rm -f "$db_backup_tmp"
    fail "PostgreSQL dump" "gzip integrity check failed"
  fi

  # Verify: contains PostgreSQL dump signature
  if ! zcat "$db_backup_tmp" 2>/dev/null | head -n 20 | grep -qE '(PostgreSQL database dump|CREATE TABLE|Dumped from database version)'; then
    rm -f "$db_backup_tmp"
    fail "PostgreSQL dump" "file does not contain PostgreSQL dump signatures"
  fi

  # Atomic move: .tmp → final
  mv "$db_backup_tmp" "$db_backup_final"
  CLEANUP_FILES=("${CLEANUP_FILES[@]/$db_backup_tmp}")

  chmod 600 "$db_backup_final"
  log_info "PostgreSQL dump created: ${db_backup_final}, size $(human_size "$db_backup_final")"

  # ── 2. Files archive ───────────────────────────────────────────────
  files_backup_final=""
  if [[ "${BACKUP_INCLUDE_FILES:-1}" == "1" ]]; then
    files_backup_tmp="${BACKUP_TMP_DIR}/mpcontrol_files_${TIMESTAMP}.tar.gz.tmp"
    files_backup_final="${BACKUP_DAILY_DIR}/mpcontrol_files_${TIMESTAMP}.tar.gz"
    CLEANUP_FILES+=("$files_backup_tmp")

    log_info "Creating project files archive: ${files_backup_final}"
    archive_project_files "$files_backup_tmp"
    validate_file "$files_backup_tmp" "Files archive"

    if ! gzip -t "$files_backup_tmp" 2>/dev/null; then
      rm -f "$files_backup_tmp"
      fail "Files archive" "gzip integrity check failed"
    fi

    mv "$files_backup_tmp" "$files_backup_final"
    CLEANUP_FILES=("${CLEANUP_FILES[@]/$files_backup_tmp}")

    chmod 600 "$files_backup_final"
    log_info "Files archive created: ${files_backup_final}, size $(human_size "$files_backup_final")"
  fi

  # ── 3. Encryption ──────────────────────────────────────────────────
  local db_encrypted files_encrypted
  db_encrypted="$(encrypt_if_enabled "$db_backup_final")"
  if [[ "$db_encrypted" != "$db_backup_final" ]]; then
    db_backup_final="$db_encrypted"
    log_info "Database dump encrypted: ${db_backup_final}"
  fi

  if [[ -n "$files_backup_final" ]]; then
    files_encrypted="$(encrypt_if_enabled "$files_backup_final")"
    if [[ "$files_encrypted" != "$files_backup_final" ]]; then
      files_backup_final="$files_encrypted"
      log_info "Files archive encrypted: ${files_backup_final}"
    fi
  fi

  # ── 4. Full archive (for restore.sh compatibility) ─────────────────
  local full_backup_tmp full_backup_final
  full_backup_tmp="${BACKUP_TMP_DIR}/mpcontrol_full_${TIMESTAMP}.tar.gz.tmp"
  full_backup_final="${BACKUP_DAILY_DIR}/mpcontrol_full_${TIMESTAMP}.tar.gz"
  CLEANUP_FILES+=("$full_backup_tmp")

  local full_items
  full_items=("$(basename "$db_backup_final")")
  if [[ -n "$files_backup_final" ]]; then
    full_items+=("$(basename "$files_backup_final")")
  fi
  if ! tar -czf "$full_backup_tmp" -C "$BACKUP_DAILY_DIR" "${full_items[@]}" 2>&1; then
    rm -f "$full_backup_tmp"
    fail "Full archive" "tar failed"
  fi
  validate_file "$full_backup_tmp" "Full archive"
  mv "$full_backup_tmp" "$full_backup_final"
  CLEANUP_FILES=("${CLEANUP_FILES[@]/$full_backup_tmp}")
  chmod 600 "$full_backup_final"
  log_info "Full archive created: ${full_backup_final}, size $(human_size "$full_backup_final")"

  # ── 5. Manifest ────────────────────────────────────────────────────
  local manifest
  manifest="${BACKUP_DAILY_DIR}/manifest_${TIMESTAMP}.json"
  {
    local db_sha files_sha
    db_sha="$(sha256sum "$db_backup_final" | cut -d' ' -f1)"
    files_sha=""
    if [[ -n "$files_backup_final" && -f "$files_backup_final" ]]; then
      files_sha="$(sha256sum "$files_backup_final" | cut -d' ' -f1)"
    fi
    python3 - "$manifest" "$TIMESTAMP" "$backup_type" "$db_backup_final" "$(file_size "$db_backup_final")" \
      "$db_sha" "$files_backup_final" "$(file_size "$files_backup_final" || echo 0)" \
      "$files_sha" "$full_backup_final" "$(file_size "$full_backup_final" || echo 0)" \
      "$(sha256sum "$full_backup_final" | cut -d' ' -f1)" <<'PY'
import json, sys
m = {
    "backup_id": sys.argv[2],
    "type": sys.argv[3],
    "created_at": sys.argv[2].replace("_", " ").replace("-", "-"),
    "files": []
}
if sys.argv[4]:
    m["files"].append({"path": sys.argv[4], "size_bytes": int(sys.argv[5] or 0), "sha256": sys.argv[6] or ""})
if sys.argv[7]:
    m["files"].append({"path": sys.argv[7], "size_bytes": int(sys.argv[8] or 0), "sha256": sys.argv[9] or ""})
if sys.argv[10]:
    m["files"].append({"path": sys.argv[10], "size_bytes": int(sys.argv[11] or 0), "sha256": sys.argv[12] or ""})
with open(sys.argv[1], "w") as f:
    json.dump(m, f, indent=2)
    f.write("\n")
PY
  }
  chmod 600 "$manifest"
  log_info "Manifest created: ${manifest}"

  # ── 6. Retention ───────────────────────────────────────────────────
  local daily_ret="${BACKUP_DAILY_RETENTION_DAYS:-14}"
  local weekly_ret="${BACKUP_WEEKLY_RETENTION_DAYS:-56}"
  local monthly_ret="${BACKUP_MONTHLY_RETENTION_DAYS:-180}"

  cleanup_retention "$BACKUP_DAILY_DIR" "$daily_ret" "daily"
  cleanup_retention "$BACKUP_WEEKLY_DIR" "$weekly_ret" "weekly"
  cleanup_retention "$BACKUP_MONTHLY_DIR" "$monthly_ret" "monthly"
  # Clean tmp files older than 1 day
  cleanup_retention "$BACKUP_TMP_DIR" 1 "tmp"

  # Copy to weekly/monthly if applicable
  if [[ "$backup_type" == "weekly" ]]; then
    mkdir -p "$BACKUP_WEEKLY_DIR"
    cp "$db_backup_final" "$BACKUP_WEEKLY_DIR/"
    [[ -n "$files_backup_final" && -f "$files_backup_final" ]] && \
      cp "$files_backup_final" "$BACKUP_WEEKLY_DIR/"
    log_info "Copied backup to weekly directory"
  elif [[ "$backup_type" == "monthly" ]]; then
    mkdir -p "$BACKUP_MONTHLY_DIR"
    cp "$db_backup_final" "$BACKUP_MONTHLY_DIR/"
    [[ -n "$files_backup_final" && -f "$files_backup_final" ]] && \
      cp "$files_backup_final" "$BACKUP_MONTHLY_DIR/"
    log_info "Copied backup to monthly directory"
  fi

  # ── 7. Notification ────────────────────────────────────────────────
  local END_SEC duration_str
  END_SEC="$(date '+%s')"
  duration_str="$(duration $((END_SEC - START_SEC)))"

  notify_telegram "Backup completed

Server: $(hostname -s 2>/dev/null || echo unknown)
Date: $(date '+%d.%m.%Y %H:%M')
Type: ${backup_type}
Duration: ${duration_str}

DB: $(basename "$db_backup_final") ($(human_size "$db_backup_final"))
$([[ -n "$files_backup_final" ]] && echo "Files: $(basename "$files_backup_final") ($(human_size "$files_backup_final"))")
Full: $(basename "$full_backup_final") ($(human_size "$full_backup_final"))

Path: ${BACKUP_DAILY_DIR}"
  log_info "${backup_type^} backup completed successfully in ${duration_str}"
}

main "$@"
