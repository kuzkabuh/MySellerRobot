#!/usr/bin/env bash
# version: 1.9.5
# description: First-time production installer for MP Control on Ubuntu.
# updated: 2026-05-31

set -Eeuo pipefail

REPO_URL="${REPO_URL:-https://github.com/kuzkabuh/MySellerRobot.git}"
BRANCH="${BRANCH:-main}"
PROJECT_USER="${PROJECT_USER:-mpcontrol}"
PROJECT_DIR="${PROJECT_DIR:-/opt/mpcontrol}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
SSL_EMAIL="${SSL_EMAIL:-}"
SKIP_SSL="${SKIP_SSL:-0}"
SKIP_DNS_CHECK="${SKIP_DNS_CHECK:-0}"
DOMAINS=()
SSL_DOMAINS=()
BOT_WEBHOOK_HOST=""
PUBLIC_HEALTH_URL=""
PUBLIC_SERVER_NAMES=""
APP_SERVER_NAMES=""
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
LOG_FILE="${LOG_FILE:-/var/log/mpcontrol-install.log}"

mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

log_info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: $*"; }
log_warn() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: $*"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    log_error "Run install.sh as root or via sudo."
    exit 1
  fi
}

check_command() {
  command -v "$1" >/dev/null 2>&1
}

detect_ubuntu() {
  if [[ ! -f /etc/os-release ]]; then
    log_error "Cannot detect operating system."
    exit 1
  fi
  # shellcheck disable=SC1091
  source /etc/os-release
  if [[ "${ID:-}" != "ubuntu" ]]; then
    log_error "Only Ubuntu 22.04/24.04 LTS is supported. Detected: ${PRETTY_NAME:-unknown}."
    exit 1
  fi
  case "${VERSION_ID:-}" in
    22.04|24.04) log_info "Detected supported Ubuntu ${VERSION_ID}." ;;
    *) log_warn "Ubuntu ${VERSION_ID:-unknown} is not explicitly tested; continuing carefully." ;;
  esac
}

install_dependencies() {
  log_info "Installing base packages, Nginx, Certbot, and DNS tools."
  apt-get update
  apt-get install -y ca-certificates curl gnupg git nginx certbot python3-certbot-nginx dnsutils openssl python3-cryptography
}

install_docker() {
  if check_command docker && docker compose version >/dev/null 2>&1; then
    log_info "Docker and Docker Compose plugin are already installed."
    systemctl enable --now docker
    return
  fi
  log_info "Installing Docker Engine and Docker Compose plugin."
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  # shellcheck disable=SC1091
  source /etc/os-release
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
}

create_user() {
  if id "$PROJECT_USER" >/dev/null 2>&1; then
    log_info "System user ${PROJECT_USER} already exists."
  else
    log_info "Creating system user ${PROJECT_USER}."
    useradd --system --create-home --shell /bin/bash "$PROJECT_USER"
  fi
  usermod -aG docker "$PROJECT_USER" || true
}

ensure_project_ownership() {
  if [[ ! -e "$PROJECT_DIR" ]]; then
    return
  fi
  local owner expected_uid
  owner="$(stat -c '%U' "$PROJECT_DIR" 2>/dev/null || echo unknown)"
  expected_uid="$(id -u "$PROJECT_USER")"
  if [[ "$owner" != "$PROJECT_USER" ]]; then
    log_warn "Обнаружено, что каталог ${PROJECT_DIR} принадлежит пользователю ${owner}."
    log_warn "Для корректной установки права будут приведены к пользователю ${PROJECT_USER}."
    chown -R "$PROJECT_USER:$PROJECT_USER" "$PROJECT_DIR"
  fi
  git config --global --add safe.directory "$PROJECT_DIR" || true
  runuser -u "$PROJECT_USER" -- git config --global --add safe.directory "$PROJECT_DIR" || true
  if [[ "$(stat -c '%u' "$PROJECT_DIR")" != "$expected_uid" ]]; then
    log_error "Не удалось привести владельца ${PROJECT_DIR} к ${PROJECT_USER}."
    exit 1
  fi
}

clone_repo() {
  mkdir -p "$(dirname "$PROJECT_DIR")"
  ensure_project_ownership
  if [[ -d "${PROJECT_DIR}/.git" ]]; then
    log_info "Project repository already exists at ${PROJECT_DIR}; updating refs."
    runuser -u "$PROJECT_USER" -- git -C "$PROJECT_DIR" fetch origin "$BRANCH"
    runuser -u "$PROJECT_USER" -- git -C "$PROJECT_DIR" checkout "$BRANCH"
    runuser -u "$PROJECT_USER" -- git -C "$PROJECT_DIR" pull --ff-only origin "$BRANCH"
  elif [[ -e "$PROJECT_DIR" && -n "$(find "$PROJECT_DIR" -mindepth 1 -maxdepth 1 2>/dev/null)" ]]; then
    log_error "${PROJECT_DIR} exists and is not an empty Git repository. Aborting."
    exit 1
  else
    log_info "Cloning ${REPO_URL} branch ${BRANCH} into ${PROJECT_DIR}."
    mkdir -p "$PROJECT_DIR"
    chown "$PROJECT_USER:$PROJECT_USER" "$PROJECT_DIR"
    runuser -u "$PROJECT_USER" -- git clone --branch "$BRANCH" "$REPO_URL" "$PROJECT_DIR"
  fi
  mkdir -p "${PROJECT_DIR}/logs/deploy" "${PROJECT_DIR}/backups" "${PROJECT_DIR}/public"
  chown -R "$PROJECT_USER:$PROJECT_USER" "$PROJECT_DIR"
  git config --global --add safe.directory "$PROJECT_DIR" || true
}

prepare_env() {
  cd "$PROJECT_DIR"
  if [[ ! -f .env ]]; then
    log_warn ".env was not found. Creating it from .env.example."
    cp .env.example .env
    chown "$PROJECT_USER:$PROJECT_USER" .env
    chmod 600 .env
    log_warn "Edit ${PROJECT_DIR}/.env and fill production secrets before re-running install.sh."
  else
    log_info ".env already exists and will not be overwritten."
    chown "$PROJECT_USER:$PROJECT_USER" .env
    chmod 600 .env
  fi
}

env_value() {
  local key="$1"
  grep -E "^${key}=" "${PROJECT_DIR}/.env" | tail -n 1 | cut -d '=' -f 2- | sed 's/^"//;s/"$//;s/^'\''//;s/'\''$//'
}

url_host() {
  python3 - "$1" <<'PY'
import sys
from urllib.parse import urlparse

host = urlparse(sys.argv[1]).hostname or ""
print(host)
PY
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
  local base_url
  for key in API_BASE_URL WEB_APP_BASE_URL WEB_BASE_URL PUBLIC_SITE_URL; do
    base_url="$(env_value "$key")"
    if [[ -n "$base_url" ]]; then
      PUBLIC_HEALTH_URL="$(with_health_path "$base_url")"
      return
    fi
  done
  log_error "Set API_BASE_URL, WEB_APP_BASE_URL, WEB_BASE_URL, or PUBLIC_SITE_URL in ${PROJECT_DIR}/.env."
  exit 1
}

load_domains_from_env() {
  local key value host public_host
  DOMAINS=()
  SSL_DOMAINS=()
  BOT_WEBHOOK_HOST=""
  public_host="$(url_host "$(env_value "PUBLIC_SITE_URL")")"
  if [[ -n "$public_host" ]]; then
    DOMAINS+=("$public_host" "www.${public_host}")
    PUBLIC_SERVER_NAMES="${public_host} www.${public_host}"
  fi

  APP_SERVER_NAMES=""
  for key in WEB_APP_BASE_URL API_BASE_URL BOT_WEBHOOK_BASE_URL; do
    value="$(env_value "$key")"
    [[ -z "$value" ]] && continue
    host="$(url_host "$value")"
    if [[ -n "$host" && " ${APP_SERVER_NAMES} " != *" ${host} "* ]]; then
      APP_SERVER_NAMES="${APP_SERVER_NAMES:+${APP_SERVER_NAMES} }${host}"
      DOMAINS+=("$host")
    fi
  done
  BOT_WEBHOOK_HOST="$(url_host "$(env_value "BOT_WEBHOOK_BASE_URL")")"
  if [[ -z "$PUBLIC_SERVER_NAMES" || -z "$APP_SERVER_NAMES" ]]; then
    log_error "PUBLIC_SITE_URL and one of WEB_APP_BASE_URL/API_BASE_URL must contain valid hosts."
    exit 1
  fi
  if [[ -z "$BOT_WEBHOOK_HOST" ]]; then
    log_error "BOT_WEBHOOK_BASE_URL must contain a valid host, for example https://bot.mpcontrol.online."
    exit 1
  fi
}

validate_env() {
  log_info "Validating required environment variables."
  local missing=()
  local insecure=()
  for key in "${REQUIRED_ENV[@]}"; do
    local value
    value="$(env_value "$key" || true)"
    if [[ -z "$value" ]]; then
      missing+=("$key")
      continue
    fi
    case "$value" in
      change-me|change_me|PASTE_*|*replace_me*|*example.com*|seller_bot)
        insecure+=("$key")
        ;;
    esac
  done
  if [[ "${#missing[@]}" -gt 0 || "${#insecure[@]}" -gt 0 ]]; then
    [[ "${#missing[@]}" -gt 0 ]] && log_error "Missing env variables: ${missing[*]}"
    [[ "${#insecure[@]}" -gt 0 ]] && log_error "Replace placeholder/insecure env values: ${insecure[*]}"
    log_error "Fix ${PROJECT_DIR}/.env and re-run install.sh."
    exit 1
  fi
  validate_secret_values
  resolve_public_health_url
  load_domains_from_env
}

validate_secret_values() {
  log_info "Validating APP_SECRET_KEY and ENCRYPTION_KEY."
  local app_secret encryption_key
  app_secret="$(env_value "APP_SECRET_KEY")"
  encryption_key="$(env_value "ENCRYPTION_KEY")"

  if [[ "${#app_secret}" -lt 32 ]]; then
    log_error "APP_SECRET_KEY is too short. Generate it with: openssl rand -hex 32"
    exit 1
  fi

  ENCRYPTION_KEY="$encryption_key" python3 - <<'PY' || {
import os
from cryptography.fernet import Fernet

Fernet(os.environ["ENCRYPTION_KEY"].encode())
PY
    log_error "ENCRYPTION_KEY is not a valid Fernet key."
    log_error "Generate it with: docker run --rm python:3.12-slim sh -c \"pip install cryptography >/dev/null 2>&1 && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'\""
    log_error "If this server uses an existing database, do not change ENCRYPTION_KEY or old marketplace API keys cannot be decrypted."
    exit 1
  }
}

write_landing_placeholder() {
  if [[ -f "${PROJECT_DIR}/public/index.html" ]]; then
    log_info "Public landing page already exists; keeping ${PROJECT_DIR}/public/index.html."
    write_service_unavailable_page
    chown -R "$PROJECT_USER:$PROJECT_USER" "${PROJECT_DIR}/public"
    return
  fi

  cat > "${PROJECT_DIR}/public/index.html" <<'HTML'
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MP Control</title>
  <style>
    body { margin:0; font-family:Arial,sans-serif; background:#f5f7fb; color:#202632; }
    main { min-height:100vh; display:grid; place-items:center; padding:24px; text-align:center; }
    h1 { margin:0 0 10px; font-size:36px; }
    p { color:#667085; font-size:18px; }
  </style>
</head>
<body><main><div><h1>MP Control</h1><p>Сервис аналитики маркетплейсов готовится к запуску.</p></div></main></body>
</html>
HTML
  write_service_unavailable_page
  chown -R "$PROJECT_USER:$PROJECT_USER" "${PROJECT_DIR}/public"
}

write_service_unavailable_page() {
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
  log_info "Configuring host Nginx for MP Control domains."
  write_landing_placeholder
  sed "s#__PROJECT_DIR__#${PROJECT_DIR}#g" \
    "${PROJECT_DIR}/deploy/nginx/mpcontrol.conf.template" |
    sed "s#__PUBLIC_SERVER_NAMES__#${PUBLIC_SERVER_NAMES}#g" |
    sed "s#__APP_SERVER_NAMES__#${APP_SERVER_NAMES}#g" \
    > /etc/nginx/sites-available/mpcontrol.conf
  ln -sfn /etc/nginx/sites-available/mpcontrol.conf /etc/nginx/sites-enabled/mpcontrol.conf
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
  systemctl enable --now nginx
  systemctl reload nginx
}

configure_telegram_update_bridge() {
  log_info "Configuring Telegram deploy trigger bridge."
  mkdir -p "${PROJECT_DIR}/runtime"
  chown -R "$PROJECT_USER:$PROJECT_USER" "${PROJECT_DIR}/runtime"
  sed -e "s#__PROJECT_DIR__#${PROJECT_DIR}#g" -e "s#__PROJECT_USER__#${PROJECT_USER}#g" \
    "${PROJECT_DIR}/deploy/systemd/mpcontrol-telegram-update.service.template" \
    > /etc/systemd/system/mpcontrol-telegram-update.service
  sed -e "s#__PROJECT_DIR__#${PROJECT_DIR}#g" \
    "${PROJECT_DIR}/deploy/systemd/mpcontrol-telegram-update.path.template" \
    > /etc/systemd/system/mpcontrol-telegram-update.path
  systemctl daemon-reload
  systemctl enable --now mpcontrol-telegram-update.path
}

configure_backup_timer() {
  log_info "Configuring daily backup timer."
  mkdir -p "${PROJECT_DIR}/backups" "${PROJECT_DIR}/logs"
  chown -R "$PROJECT_USER:$PROJECT_USER" "${PROJECT_DIR}/backups" "${PROJECT_DIR}/logs"
  sed "s#/opt/mpcontrol#${PROJECT_DIR}#g" \
    "${PROJECT_DIR}/deploy/systemd/mpcontrol-backup.service" \
    > /etc/systemd/system/mpcontrol-backup.service
  cp "${PROJECT_DIR}/deploy/systemd/mpcontrol-backup.timer" /etc/systemd/system/mpcontrol-backup.timer
  systemctl daemon-reload
  systemctl enable --now mpcontrol-backup.timer
}

server_ipv4() {
  curl -fsS4 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}'
}

resolve_ipv4_records() {
  local domain="$1"
  if check_command dig; then
    dig +short A "$domain" | sort -u | tr '\n' ' '
  else
    getent ahostsv4 "$domain" | awk '{print $1}' | sort -u | tr '\n' ' '
  fi
}

prepare_ssl_domains() {
  SSL_DOMAINS=()
  if [[ "$SKIP_DNS_CHECK" == "1" ]]; then
    log_warn "Skipping DNS check because SKIP_DNS_CHECK=1."
    SSL_DOMAINS=("${DOMAINS[@]}")
    return
  fi
  local ip
  ip="$(server_ipv4)"
  log_info "Server public IPv4 detected as ${ip}."
  for domain in "${DOMAINS[@]}"; do
    local resolved
    resolved="$(resolve_ipv4_records "$domain")"
    if [[ -z "$resolved" || " $resolved " != *" $ip "* ]]; then
      if [[ "$domain" == "$BOT_WEBHOOK_HOST" ]]; then
        log_error "${domain} is required for Telegram webhook SSL but does not resolve to ${ip}."
        log_error "Fix the DNS A record: ${domain} -> ${ip}, wait for propagation, then re-run install.sh."
        log_error "Current A records: ${resolved:-none}"
        exit 1
      fi
      log_warn "${domain} does not resolve to ${ip}. Current A records: ${resolved:-none}. It will be skipped for this Certbot run."
    else
      log_info "${domain} resolves correctly."
      SSL_DOMAINS+=("$domain")
    fi
  done

  if [[ " ${SSL_DOMAINS[*]} " != *" ${BOT_WEBHOOK_HOST} "* ]]; then
    log_error "${BOT_WEBHOOK_HOST} is missing from the SSL domain list. Telegram webhook cannot work without it."
    exit 1
  fi
  if [[ "${#SSL_DOMAINS[@]}" -eq 0 ]]; then
    log_error "No domains are eligible for Certbot. Fix DNS records or run with SKIP_SSL=1."
    exit 1
  fi
}

obtain_ssl() {
  if [[ "$SKIP_SSL" == "1" ]]; then
    log_warn "Skipping Certbot because SKIP_SSL=1."
    return
  fi
  if [[ -z "$SSL_EMAIL" ]]; then
    log_error "Set SSL_EMAIL to request Let's Encrypt certificates."
    exit 1
  fi
  prepare_ssl_domains
  log_info "Requesting Let's Encrypt certificates with Certbot."
  local certbot_args=()
  local domain
  log_info "Certbot domains: ${SSL_DOMAINS[*]}"
  for domain in "${SSL_DOMAINS[@]}"; do
    certbot_args+=("-d" "$domain")
  done
  certbot --nginx --non-interactive --agree-tos --redirect --email "$SSL_EMAIL" "${certbot_args[@]}"
  certbot renew --dry-run
  nginx -t
  systemctl reload nginx
  verify_bot_certificate_san
  log_info "Installed Certbot certificates:"
  certbot certificates || true
}

configure_telegram_webhook() {
  cd "$PROJECT_DIR"
  local enabled token base path secret app_env webhook_url delete_response set_response
  enabled="$(env_value "BOT_WEBHOOK_ENABLED")"
  if [[ "$enabled" != "true" && "$enabled" != "1" ]]; then
    log_warn "Skipping Telegram webhook setup because BOT_WEBHOOK_ENABLED=${enabled:-false}."
    return
  fi

  token="$(env_value "BOT_TOKEN")"
  base="$(env_value "BOT_WEBHOOK_BASE_URL")"
  path="$(env_value "BOT_WEBHOOK_PATH")"
  secret="$(env_value "BOT_WEBHOOK_SECRET")"
  if [[ -z "$secret" ]]; then
    secret="$(env_value "TELEGRAM_WEBHOOK_SECRET")"
  fi
  app_env="$(env_value "APP_ENV")"
  path="${path:-/webhook/telegram}"

  if [[ -z "$token" || -z "$base" ]]; then
    log_error "BOT_TOKEN and BOT_WEBHOOK_BASE_URL are required to configure Telegram webhook."
    exit 1
  fi
  if [[ -z "$secret" && "$app_env" =~ ^(production|prod|staging)$ ]]; then
    log_error "BOT_WEBHOOK_SECRET or TELEGRAM_WEBHOOK_SECRET is required for Telegram webhook in production."
    exit 1
  fi

  webhook_url="${base%/}${path}"
  log_info "Resetting Telegram webhook before setting ${webhook_url}."
  delete_response="$(curl -fsS "https://api.telegram.org/bot${token}/deleteWebhook?drop_pending_updates=false")" || {
    log_error "Failed to delete previous Telegram webhook."
    exit 1
  }
  echo "$delete_response" | grep -q '"ok":true' || {
    log_error "Telegram deleteWebhook failed: ${delete_response}"
    exit 1
  }

  local curl_args=(
    -fsS
    -X POST
    "https://api.telegram.org/bot${token}/setWebhook"
    -F "url=${webhook_url}"
    -F 'allowed_updates=["message","callback_query"]'
  )
  if [[ -n "$secret" ]]; then
    curl_args+=(-F "secret_token=${secret}")
  fi
  set_response="$(curl "${curl_args[@]}")" || {
    log_error "Failed to set Telegram webhook."
    exit 1
  }
  echo "$set_response" | grep -q '"ok":true' || {
    log_error "Telegram setWebhook failed: ${set_response}"
    exit 1
  }
  log_info "Telegram webhook configured successfully."
  log_info "Telegram getWebhookInfo:"
  curl -fsS "https://api.telegram.org/bot${token}/getWebhookInfo" || true
  echo
}

verify_bot_certificate_san() {
  if [[ -z "$BOT_WEBHOOK_HOST" ]]; then
    log_error "BOT_WEBHOOK_HOST is empty; cannot verify Telegram webhook certificate."
    exit 1
  fi
  log_info "Checking certificate SAN for ${BOT_WEBHOOK_HOST}."
  local san_output
  san_output="$(
    echo | openssl s_client -connect "${BOT_WEBHOOK_HOST}:443" -servername "$BOT_WEBHOOK_HOST" 2>/dev/null |
      openssl x509 -noout -issuer -subject -dates -ext subjectAltName
  )" || {
    log_error "Failed to read certificate for ${BOT_WEBHOOK_HOST}:443."
    exit 1
  }
  echo "$san_output"
  if [[ "$san_output" != *"DNS:${BOT_WEBHOOK_HOST}"* ]]; then
    log_error "Certificate SAN does not contain DNS:${BOT_WEBHOOK_HOST}."
    log_error "Telegram will reject webhook HTTPS with certificate verify failed."
    exit 1
  fi
  log_info "Telegram webhook SSL certificate contains DNS:${BOT_WEBHOOK_HOST}."
}

prepare_alembic_version_table() {
  cd "$PROJECT_DIR"
  log_info "Preparing Alembic version table."

  local pg_user pg_db
  pg_user="$(env_value "POSTGRES_USER")"
  pg_db="$(env_value "POSTGRES_DB")"

  if [[ -z "$pg_user" || -z "$pg_db" ]]; then
    log_error "POSTGRES_USER and POSTGRES_DB must be set before preparing Alembic version table."
    exit 1
  fi

  docker compose -f "$COMPOSE_FILE" exec -T postgres \
    psql -U "$pg_user" -d "$pg_db" \
    -c "CREATE TABLE IF NOT EXISTS alembic_version (
          version_num VARCHAR(255) NOT NULL,
          CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
        );"

  docker compose -f "$COMPOSE_FILE" exec -T postgres \
    psql -U "$pg_user" -d "$pg_db" \
    -c "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255);"

  docker compose -f "$COMPOSE_FILE" exec -T postgres \
    psql -U "$pg_user" -d "$pg_db" \
    -c "\d alembic_version" || true
}

start_services() {
  cd "$PROJECT_DIR"
  log_info "Building production images."
  docker compose -f "$COMPOSE_FILE" build
  log_info "Starting PostgreSQL and Redis."
  docker compose -f "$COMPOSE_FILE" up -d postgres redis
  prepare_alembic_version_table
  log_info "Running Alembic migrations."
  docker compose -f "$COMPOSE_FILE" run --rm api alembic upgrade head
  log_info "Starting application services."
  docker compose -f "$COMPOSE_FILE" up -d
}

healthcheck() {
  log_info "Checking local API health."
  for attempt in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:8000/health >/dev/null; then
      log_info "Local API is ready."
      break
    fi
    log_warn "Local API is still starting, attempt ${attempt}/60."
    sleep 2
  done
  curl -fsS http://127.0.0.1:8000/health >/dev/null || {
    log_error "Local API did not become healthy."
    docker compose -f "$COMPOSE_FILE" logs --tail=200 api || true
    exit 1
  }
  if [[ "$SKIP_SSL" != "1" ]]; then
    log_info "Checking public API health."
    curl -fsS "$PUBLIC_HEALTH_URL" >/dev/null
  fi
}

print_summary() {
  log_info "MP Control installation completed."
  echo
  echo "Project: ${PROJECT_DIR}"
  echo "Compose: docker compose -f ${PROJECT_DIR}/${COMPOSE_FILE} ps"
  echo "Logs:    docker compose -f ${PROJECT_DIR}/${COMPOSE_FILE} logs -f api bot worker"
  echo "Health:  ${PUBLIC_HEALTH_URL}"
}

main() {
  require_root
  detect_ubuntu
  install_dependencies
  install_docker
  create_user
  clone_repo
  prepare_env
  validate_env
  configure_nginx
  configure_telegram_update_bridge
  configure_backup_timer
  start_services
  obtain_ssl
  configure_telegram_webhook
  healthcheck
  print_summary
}

main "$@"
