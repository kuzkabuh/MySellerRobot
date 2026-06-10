#!/usr/bin/env bash
# Daily PostgreSQL and important files backup for MP Control production.

set -Eeuo pipefail

# Определяем корень проекта: сначала из DEPLOY_PROJECT_DIR (.env), затем из директории скрипта
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${PARENT_DIR}/.env"

# Загружаем .env, чтобы получить DEPLOY_PROJECT_DIR и остальные настройки
load_env() {
  if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC2046
    export $(grep -v '^\s*#' "$ENV_FILE" | grep -v '^\s*$' | grep -v '^BACKUP_ENCRYPTION_PASSWORD=' | xargs -d '\n' 2>/dev/null || true)
    # Дозагружаем BACKUP_ENCRYPTION_PASSWORD отдельно (может содержать спецсимволы)
    local enc_pass
    enc_pass="$(grep -E '^BACKUP_ENCRYPTION_PASSWORD=' "$ENV_FILE" | tail -1 | cut -d '=' -f 2- || true)"
    if [[ -n "$enc_pass" ]]; then
      BACKUP_ENCRYPTION_PASSWORD="$enc_pass"
    fi
    export BACKUP_ENCRYPTION_PASSWORD
  else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: .env не найден: ${ENV_FILE}"
  fi
}

load_env

# После загрузки .env определяем PROJECT_DIR из DEPLOY_PROJECT_DIR
PROJECT_DIR="${DEPLOY_PROJECT_DIR:-$PARENT_DIR}"
COMPOSE_FILE="${COMPOSE_FILE:-${PROJECT_DIR}/docker-compose.prod.yml}"
LOG_FILE="${LOG_FILE:-${PROJECT_DIR}/logs/backup.log}"

mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: $*"; }
log_warn() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: $*"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; }

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
    # Не логируем токен бота, не выводим секреты
    local http_code=0
    http_code=$(curl -fsS -o /dev/null -w "%{http_code}" \
      -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
      -d "chat_id=${admin_id}" \
      --data-urlencode "text=${text}" \
      2>/dev/null) || http_code=$?
    if [[ "$http_code" =~ ^(429|5[0-9][0-9])$ ]]; then
      log_warn "Telegram вернул HTTP ${http_code} для админа ${admin_id}, уведомление не отправлено"
    elif [[ "$http_code" != "200" ]]; then
      log_warn "Не удалось отправить Telegram-уведомление админу ${admin_id} (HTTP ${http_code})"
    fi
  done
}

fail() {
  local stage="$1"
  local message="$2"
  log_error "${stage}: ${message}"
  notify_telegram "Ошибка ежедневного бэкапа MP Control

Дата: $(date '+%d.%m.%Y %H:%M')
Этап: ${stage}
Ошибка: ${message}

Проверьте сервер и логи:
docker compose -f ${COMPOSE_FILE} logs --tail=200 postgres" || true
  exit 1
}

fail_archive_security() {
  local reason="$1"
  log_error "Проверка безопасности архива: ${reason}"
  notify_telegram "Ошибка ежедневного бэкапа MP Control

Дата: $(date '+%d.%m.%Y %H:%M')
Этап: Проверка безопасности архива
Причина: ${reason}
Решение: включите BACKUP_ENCRYPTION_ENABLED=1 и задайте пароль шифрования." || true
  exit 1
}

check_archive_security() {
  if [[ "${BACKUP_INCLUDE_FILES:-1}" != "1" ]]; then
    return 0
  fi
  # В production архив с .env требует шифрования
  if [[ "${APP_ENV:-local}" =~ ^(production|prod|staging)$ ]] \
    && [[ "${BACKUP_ENCRYPTION_ENABLED:-0}" != "1" ]] \
    && [[ "${BACKUP_ALLOW_PLAINTEXT_SECRETS:-0}" != "1" ]]; then
    fail_archive_security "BACKUP_ENCRYPTION_ENABLED=1, но BACKUP_ENCRYPTION_PASSWORD пустой."
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
      --passphrase "$BACKUP_ENCRYPTION_PASSWORD" "$path"
    chmod 600 "${path}.gpg"
    rm -f "$path"
    echo "${path}.gpg"
  else
    fail "Шифрование" "openssl или gpg не найдены. Установите openssl: apt install openssl"
  fi
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
  # Если шифрование выключено и секреты не разрешены в открытом виде — исключаем .env
  local exclude_env=()
  if [[ "${BACKUP_ENCRYPTION_ENABLED:-0}" != "1" && "${BACKUP_ALLOW_PLAINTEXT_SECRETS:-0}" != "1" ]]; then
    exclude_env=("--exclude=.env")
  fi
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
    --exclude='*.pyc' \
    --exclude='postgres_data' \
    --exclude='redis_data' \
    "${exclude_env[@]}" \
    -czf "$target" \
    -C "$PROJECT_DIR" \
    .env docker-compose.prod.yml deploy nginx uploads storage runtime 2>/dev/null || true
}

main() {
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
  mkdir -p "$BACKUP_DAILY_DIR" "${backup_root}/archive" "${backup_root}/meta" "${backup_root}/env"
  chmod 700 "$backup_root"

  db_backup="${BACKUP_DAILY_DIR}/mpcontrol_db_${timestamp}.dump"
  files_backup="${BACKUP_DAILY_DIR}/mpcontrol_files_${timestamp}.tar.gz"
  full_backup="${BACKUP_DAILY_DIR}/mpcontrol_full_${timestamp}.tar.gz"

  log_info "Старт ежедневного бэкапа MP Control"
  log_info "Создание PostgreSQL dump (custom format): ${db_backup}"

  # Используем custom format .dump, чтобы избежать проблем с gzip pipe
  # Если pg_dump падает — ошибка видна в логе, а не маскируется Broken pipe
  "${compose_cmd[@]}" exec -T postgres pg_dump \
    -U "${POSTGRES_USER:-seller_bot}" \
    -d "${POSTGRES_DB:-seller_profit_bot}" \
    --format=custom \
    --no-owner \
    --no-privileges \
    > "$db_backup" || fail "PostgreSQL dump" "pg_dump завершился с ошибкой (код $?)"

  validate_file "$db_backup" "Проверка PostgreSQL dump"

  # Проверка custom dump через pg_restore -l
  if ! cat "$db_backup" | "${compose_cmd[@]}" exec -T postgres pg_restore -l >/dev/null 2>&1; then
    fail "Проверка дампа" "в файле не найдены признаки PostgreSQL dump (pg_restore -l не прошёл)"
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

  # Уведомление даже если curl вернёт 429 — не валим backup
  notify_telegram "Ежедневный бэкап MP Control выполнен

Дата: $(date '+%d.%m.%Y %H:%M')
БД: успешно
Файл БД: $(basename "$db_final")
Размер БД: $(human_size "$db_final")

Файлы проекта: $([[ -n "$files_final" ]] && echo 'успешно' || echo 'отключено')
Файл архива: $([[ -n "$files_final" ]] && basename "$files_final" || echo 'не создан')
Размер архива: $([[ -n "$files_final" ]] && human_size "$files_final" || echo 'н/д')

Старые бэкапы очищены: ${cleaned}" || true

  log_info "Ежедневный бэкап завершён успешно"
}

main "$@"
