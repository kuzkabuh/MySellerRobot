#!/usr/bin/env bash
# Daily PostgreSQL and important files backup for MP Control production.

set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/mpcontrol}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-${PROJECT_DIR}/.env}"
LOG_FILE="${LOG_FILE:-${PROJECT_DIR}/logs/backup.log}"

mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: $*"; }
log_warn() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: $*"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; }

load_env() {
  if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
  else
    log_warn ".env не найден: ${ENV_FILE}"
  fi
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "$2" "Команда $1 не найдена"
  fi
}

human_size() {
  local path="$1"
  if command -v numfmt >/dev/null 2>&1; then
    numfmt --to=iec --suffix=B --format="%.1f" "$(stat -c%s "$path")"
  else
    echo "$(stat -c%s "$path") bytes"
  fi
}

file_size() {
  stat -c%s "$1"
}

notify_telegram() {
  local text="$1"
  if [[ "${BACKUP_TELEGRAM_NOTIFY:-1}" != "1" ]]; then
    return 0
  fi
  if [[ -z "${BOT_TOKEN:-}" || -z "${ADMIN_TELEGRAM_IDS:-}" ]]; then
    log_warn "Telegram-уведомление пропущено: BOT_TOKEN или ADMIN_TELEGRAM_IDS не настроены"
    return 0
  fi
  local admin_id
  IFS=',' read -ra admins <<< "$ADMIN_TELEGRAM_IDS"
  for admin_id in "${admins[@]}"; do
    admin_id="$(echo "$admin_id" | xargs)"
    [[ -z "$admin_id" ]] && continue
    curl -fsS \
      -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
      -d "chat_id=${admin_id}" \
      --data-urlencode "text=${text}" \
      >/dev/null || log_warn "Не удалось отправить Telegram-уведомление админу ${admin_id}"
  done
}

fail() {
  local stage="$1"
  local message="$2"
  log_error "${stage}: ${message}"
  notify_telegram "❌ Ошибка ежедневного бэкапа MP Control

Дата: $(date '+%d.%m.%Y %H:%M')
Этап: ${stage}
Ошибка: ${message}

Проверьте сервер и логи:
docker compose -f ${COMPOSE_FILE} logs --tail=200 postgres"
  exit 1
}

fail_archive_security() {
  local reason="$1"
  log_error "Проверка безопасности архива: ${reason}"
  notify_telegram "❌ Ошибка ежедневного бэкапа MP Control

Дата: $(date '+%d.%m.%Y %H:%M')
Этап: Проверка безопасности архива
Причина: ${reason}
Решение: включите BACKUP_ENCRYPTION_ENABLED=1 и задайте пароль шифрования."
  exit 1
}

check_archive_security() {
  if [[ "${BACKUP_INCLUDE_FILES:-1}" != "1" ]]; then
    return 0
  fi
  if [[ "${APP_ENV:-local}" =~ ^(production|prod|staging)$ ]] \
    && [[ "${BACKUP_ENCRYPTION_ENABLED:-0}" != "1" ]] \
    && [[ "${BACKUP_ALLOW_PLAINTEXT_SECRETS:-0}" != "1" ]]; then
    fail_archive_security "бэкап содержит файлы с секретами, но шифрование отключено."
  fi
  if [[ "${BACKUP_ENCRYPTION_ENABLED:-0}" == "1" && -z "${BACKUP_ENCRYPTION_PASSWORD:-}" ]]; then
    fail_archive_security "BACKUP_ENCRYPTION_ENABLED=1, но BACKUP_ENCRYPTION_PASSWORD пустой."
  fi
}

encrypt_if_enabled() {
  local path="$1"
  if [[ "${BACKUP_ENCRYPTION_ENABLED:-0}" != "1" ]]; then
    echo "$path"
    return 0
  fi
  if [[ -z "${BACKUP_ENCRYPTION_PASSWORD:-}" ]]; then
    fail_archive_security "BACKUP_ENCRYPTION_ENABLED=1, но BACKUP_ENCRYPTION_PASSWORD пустой."
  fi
  require_command gpg "Шифрование"
  gpg --batch --yes --symmetric --cipher-algo AES256 \
    --passphrase "$BACKUP_ENCRYPTION_PASSWORD" "$path"
  chmod 600 "${path}.gpg"
  rm -f "$path"
  echo "${path}.gpg"
}

validate_file() {
  local path="$1"
  local stage="$2"
  if [[ ! -s "$path" ]]; then
    fail "$stage" "файл не создан или пустой: ${path}"
  fi
  if [[ "$(file_size "$path")" -le 1024 ]]; then
    fail "$stage" "файл подозрительно маленький: ${path}"
  fi
}

cleanup_old_backups() {
  local cleaned="нет"
  if [[ "${BACKUP_DAILY_RETENTION_DAYS:-14}" =~ ^[0-9]+$ ]]; then
    find "$BACKUP_DAILY_DIR" -type f -mtime +"${BACKUP_DAILY_RETENTION_DAYS:-14}" -delete
    cleaned="да"
  fi
  echo "$cleaned"
}

archive_project_files() {
  local target="$1"
  tar \
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
    --exclude='logs/*.log' \
    --exclude='backups' \
    --exclude='tmp' \
    --exclude='*.tmp' \
    --exclude='postgres_data' \
    --exclude='redis_data' \
    -czf "$target" \
    -C "$PROJECT_DIR" \
    .env docker-compose.prod.yml deploy nginx uploads storage runtime 2>/dev/null || true
}

main() {
  load_env
  if [[ "${BACKUP_ENABLED:-1}" != "1" ]]; then
    log_info "Бэкапы отключены: BACKUP_ENABLED=${BACKUP_ENABLED:-0}"
    exit 0
  fi
  check_archive_security

  cd "$PROJECT_DIR"
  require_command docker "Проверка Docker"
  require_command gzip "Проверка gzip"
  require_command tar "Проверка tar"
  if [[ "${BACKUP_TELEGRAM_NOTIFY:-1}" == "1" ]]; then
    require_command curl "Telegram-уведомление"
  fi

  local compose_cmd=(docker compose -f "$COMPOSE_FILE")
  if ! "${compose_cmd[@]}" ps postgres >/dev/null 2>&1; then
    fail "Проверка PostgreSQL" "контейнер postgres не найден"
  fi

  local timestamp backup_root db_backup files_backup full_backup db_final files_final cleaned
  timestamp="$(date '+%Y-%m-%d_%H-%M-%S')"
  backup_root="${BACKUP_DIR:-${PROJECT_DIR}/backups}"
  BACKUP_DAILY_DIR="${backup_root}/daily"
  mkdir -p "$BACKUP_DAILY_DIR" "${backup_root}/weekly" "${backup_root}/monthly" \
    "${backup_root}/tmp" "${backup_root}/restore"
  chmod 700 "$backup_root"

  db_backup="${BACKUP_DAILY_DIR}/mpcontrol_db_${timestamp}.sql.gz"
  files_backup="${BACKUP_DAILY_DIR}/mpcontrol_files_${timestamp}.tar.gz"
  full_backup="${BACKUP_DAILY_DIR}/mpcontrol_full_${timestamp}.tar.gz"

  log_info "Старт ежедневного бэкапа MP Control"
  log_info "Создание PostgreSQL dump: ${db_backup}"
  "${compose_cmd[@]}" exec -T postgres pg_dump \
    -U "${POSTGRES_USER:-seller_bot}" \
    -d "${POSTGRES_DB:-seller_profit_bot}" \
    --format=plain \
    --no-owner \
    --no-privileges \
    | gzip > "$db_backup" || fail "PostgreSQL dump" "pg_dump завершился с ошибкой"

  validate_file "$db_backup" "Проверка PostgreSQL dump"
  gzip -t "$db_backup" || fail "Проверка gzip" "архив БД повреждён"
  if ! gunzip -c "$db_backup" | head -n 20 | grep -Eq 'PostgreSQL database dump|CREATE TABLE|COPY '; then
    fail "Проверка дампа" "в файле не найдены признаки PostgreSQL dump"
  fi
  chmod 600 "$db_backup"
  db_final="$(encrypt_if_enabled "$db_backup")"
  log_info "Бэкап БД создан: ${db_final}, размер $(human_size "$db_final")"

  files_final=""
  if [[ "${BACKUP_INCLUDE_FILES:-1}" == "1" ]]; then
    log_info "Создание архива важных файлов: ${files_backup}"
    archive_project_files "$files_backup"
    validate_file "$files_backup" "Архив файлов"
    gzip -t "$files_backup" || fail "Проверка архива файлов" "архив файлов повреждён"
    chmod 600 "$files_backup"
    files_final="$(encrypt_if_enabled "$files_backup")"
    log_info "Архив файлов создан: ${files_final}, размер $(human_size "$files_final")"
  fi

  log_info "Создание полного архива: ${full_backup}"
  local full_items
  full_items=("$(basename "$db_final")")
  if [[ -n "$files_final" ]]; then
    full_items+=("$(basename "$files_final")")
  fi
  tar -czf "$full_backup" -C "$BACKUP_DAILY_DIR" "${full_items[@]}" \
    || fail "Полный архив" "tar завершился с ошибкой"
  validate_file "$full_backup" "Полный архив"
  gzip -t "$full_backup" || fail "Проверка полного архива" "полный архив повреждён"
  chmod 600 "$full_backup"
  log_info "Полный архив создан: ${full_backup}, размер $(human_size "$full_backup")"

  cleaned="$(cleanup_old_backups)"
  log_info "Очистка старых daily-бэкапов: ${cleaned}"

  notify_telegram "✅ Ежедневный бэкап MP Control выполнен

Дата: $(date '+%d.%m.%Y %H:%M')
БД: успешно
Файл БД: $(basename "$db_final")
Размер БД: $(human_size "$db_final")

Файлы проекта: $([[ -n "$files_final" ]] && echo 'успешно' || echo 'отключено')
Файл архива: $([[ -n "$files_final" ]] && basename "$files_final" || echo 'не создан')
Размер архива: $([[ -n "$files_final" ]] && human_size "$files_final" || echo 'н/д')

Старые бэкапы очищены: ${cleaned}"

  log_info "Ежедневный бэкап завершён успешно"
}

main "$@"
