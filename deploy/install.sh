#!/usr/bin/env bash
# version: 1.0.0
# description: First-time production installer for MP Control on Ubuntu.
# updated: 2026-05-15

set -Eeuo pipefail

REPO_URL="${REPO_URL:-https://github.com/kuzkabuh/MySellerRobot.git}"
BRANCH="${BRANCH:-main}"
PROJECT_USER="${PROJECT_USER:-mpcontrol}"
PROJECT_DIR="${PROJECT_DIR:-/opt/mpcontrol}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
SSL_EMAIL="${SSL_EMAIL:-}"
SKIP_SSL="${SKIP_SSL:-0}"
SKIP_DNS_CHECK="${SKIP_DNS_CHECK:-0}"
DOMAINS=(mpcontrol.online www.mpcontrol.online app.mpcontrol.online api.mpcontrol.online bot.mpcontrol.online)
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
  apt-get install -y ca-certificates curl gnupg git nginx certbot python3-certbot-nginx dnsutils
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

clone_repo() {
  mkdir -p "$(dirname "$PROJECT_DIR")"
  if [[ -d "${PROJECT_DIR}/.git" ]]; then
    log_info "Project repository already exists at ${PROJECT_DIR}; updating refs."
    git -C "$PROJECT_DIR" fetch origin "$BRANCH"
    git -C "$PROJECT_DIR" checkout "$BRANCH"
    git -C "$PROJECT_DIR" pull --ff-only origin "$BRANCH"
  elif [[ -e "$PROJECT_DIR" && -n "$(find "$PROJECT_DIR" -mindepth 1 -maxdepth 1 2>/dev/null)" ]]; then
    log_error "${PROJECT_DIR} exists and is not an empty Git repository. Aborting."
    exit 1
  else
    log_info "Cloning ${REPO_URL} branch ${BRANCH} into ${PROJECT_DIR}."
    git clone --branch "$BRANCH" "$REPO_URL" "$PROJECT_DIR"
  fi
  mkdir -p "${PROJECT_DIR}/logs/deploy" "${PROJECT_DIR}/backups" "${PROJECT_DIR}/public"
  chown -R "$PROJECT_USER:$PROJECT_USER" "$PROJECT_DIR"
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
  fi
}

env_value() {
  local key="$1"
  grep -E "^${key}=" "${PROJECT_DIR}/.env" | tail -n 1 | cut -d '=' -f 2- | sed 's/^"//;s/"$//'
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
      change-me|PASTE_*|*replace_me*|*seller.example.com*|seller_bot)
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
}

write_landing_placeholder() {
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
  chown -R "$PROJECT_USER:$PROJECT_USER" "${PROJECT_DIR}/public"
}

configure_nginx() {
  log_info "Configuring host Nginx for MP Control domains."
  write_landing_placeholder
  sed "s#__PROJECT_DIR__#${PROJECT_DIR}#g" \
    "${PROJECT_DIR}/deploy/nginx/mpcontrol.conf.template" > /etc/nginx/sites-available/mpcontrol.conf
  ln -sfn /etc/nginx/sites-available/mpcontrol.conf /etc/nginx/sites-enabled/mpcontrol.conf
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
  systemctl enable --now nginx
  systemctl reload nginx
}

server_ipv4() {
  curl -fsS4 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}'
}

check_dns() {
  if [[ "$SKIP_DNS_CHECK" == "1" ]]; then
    log_warn "Skipping DNS check because SKIP_DNS_CHECK=1."
    return
  fi
  local ip failures=0
  ip="$(server_ipv4)"
  log_info "Server public IPv4 detected as ${ip}."
  for domain in "${DOMAINS[@]}"; do
    local resolved
    resolved="$(getent ahostsv4 "$domain" | awk '{print $1}' | sort -u | tr '\n' ' ')"
    if [[ -z "$resolved" || " $resolved " != *" $ip "* ]]; then
      log_warn "${domain} does not resolve to ${ip}. Current A records: ${resolved:-none}"
      failures=$((failures + 1))
    else
      log_info "${domain} resolves correctly."
    fi
  done
  if [[ "$failures" -gt 0 ]]; then
    log_error "DNS is not ready. Create A records first or run with SKIP_SSL=1 SKIP_DNS_CHECK=1."
    exit 1
  fi
}

obtain_ssl() {
  if [[ "$SKIP_SSL" == "1" ]]; then
    log_warn "Skipping Certbot because SKIP_SSL=1."
    return
  fi
  if [[ -z "$SSL_EMAIL" ]]; then
    log_error "Set SSL_EMAIL=owner@example.com to request Let's Encrypt certificates."
    exit 1
  fi
  check_dns
  log_info "Requesting Let's Encrypt certificates with Certbot."
  certbot --nginx --non-interactive --agree-tos --redirect --email "$SSL_EMAIL" \
    -d mpcontrol.online \
    -d www.mpcontrol.online \
    -d app.mpcontrol.online \
    -d api.mpcontrol.online \
    -d bot.mpcontrol.online
  certbot renew --dry-run
  nginx -t
  systemctl reload nginx
}

start_services() {
  cd "$PROJECT_DIR"
  log_info "Building production images."
  docker compose -f "$COMPOSE_FILE" build
  log_info "Starting PostgreSQL and Redis."
  docker compose -f "$COMPOSE_FILE" up -d postgres redis
  log_info "Running Alembic migrations."
  docker compose -f "$COMPOSE_FILE" run --rm api alembic upgrade head
  log_info "Starting application services."
  docker compose -f "$COMPOSE_FILE" up -d
}

healthcheck() {
  log_info "Checking local API health."
  curl -fsS http://127.0.0.1:8000/health >/dev/null
  if [[ "$SKIP_SSL" != "1" ]]; then
    log_info "Checking public API health."
    curl -fsS https://api.mpcontrol.online/health >/dev/null
  fi
}

print_summary() {
  log_info "MP Control installation completed."
  echo
  echo "Project: ${PROJECT_DIR}"
  echo "Compose: docker compose -f ${PROJECT_DIR}/${COMPOSE_FILE} ps"
  echo "Logs:    docker compose -f ${PROJECT_DIR}/${COMPOSE_FILE} logs -f api bot worker"
  echo "Health:  https://api.mpcontrol.online/health"
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
  start_services
  obtain_ssl
  healthcheck
  print_summary
}

main "$@"
