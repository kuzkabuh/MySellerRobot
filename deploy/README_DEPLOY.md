# version: 1.8.1
# description: Production deployment guide for MP Control on Ubuntu VPS.
# updated: 2026-05-21

# Production-развёртывание MP Control

Эта инструкция описывает первый запуск и обновление MP Control на VPS с Ubuntu 22.04 LTS
или Ubuntu 24.04 LTS.

## Архитектура

- Приложение запускается через Docker Compose production stack:
  `postgres`, `redis`, `api`, `bot`, `worker`.
- Nginx и Certbot устанавливаются на хосте.
- Telegram webhook работает на отдельном домене `bot.mpcontrol.online`.
- FastAPI и web-кабинет работают в одном `api`-контейнере на `127.0.0.1:8000`.

## DNS

Перед установкой создайте A-записи на IP сервера:

| Host | Значение |
|---|---|
| `@` | IP сервера |
| `www` | IP сервера |
| `app` | IP сервера |
| `api` | IP сервера |
| `bot` | IP сервера |

Итоговые домены:

- `https://example.com` — публичная заглушка/лендинг;
- `https://www.example.com` — alias лендинга;
- `https://app.example.com` — web-кабинет;
- `https://api.example.com` — backend API;
- `https://bot.mpcontrol.online` — Telegram webhook.

## GitHub-доступ

### Публичный репозиторий

Можно использовать HTTPS:

```bash
REPO_URL="https://github.com/kuzkabuh/MySellerRobot.git"
```

### Приватный репозиторий

Рекомендуемый способ — GitHub Deploy Key.

На сервере:

```bash
sudo -u mpcontrol ssh-keygen -t ed25519 -C "mpcontrol-deploy" -f /home/mpcontrol/.ssh/id_ed25519
sudo -u mpcontrol cat /home/mpcontrol/.ssh/id_ed25519.pub
```

Добавьте публичный ключ в GitHub:

Repository → Settings → Deploy keys → Add deploy key.

После этого используйте SSH URL:

```bash
REPO_URL="git@github.com:kuzkabuh/MySellerRobot.git"
```

## Первый запуск

Минимальный сценарий:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/kuzkabuh/MySellerRobot.git /tmp/mpcontrol-src
cd /tmp/mpcontrol-src
sudo REPO_URL="https://github.com/kuzkabuh/MySellerRobot.git" \
  BRANCH="main" \
  SSL_EMAIL="owner@example.com" \
  bash deploy/install.sh
```

Если DNS ещё не готов и нужно только поднять контейнеры без SSL:

```bash
sudo SKIP_SSL=1 SKIP_DNS_CHECK=1 bash deploy/install.sh
```

## Настройка `.env`

`install.sh` никогда не перезаписывает существующий `/opt/mpcontrol/.env`.

Если `.env` отсутствует, скрипт создаст его из `.env.example` и остановится с понятной ошибкой,
если обязательные значения не заполнены.

Обязательно заполните:

- `APP_ENV=production`;
- `APP_DEBUG=false`;
- `APP_SECRET_KEY`;
- `ENCRYPTION_KEY`;
- `BOT_TOKEN`;
- `ADMIN_TELEGRAM_IDS`;
- `POSTGRES_DB`;
- `POSTGRES_USER`;
- `POSTGRES_PASSWORD`;
- `DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@postgres:5432/DB`;
- `REDIS_URL=redis://redis:6379/0`;
- `WEB_BASE_URL=https://app.example.com`;
- `WEB_APP_BASE_URL=https://app.example.com`;
- `API_BASE_URL=https://api.example.com`;
- `PUBLIC_SITE_URL=https://example.com`.
- `BOT_WEBHOOK_BASE_URL=https://bot.mpcontrol.online`;
- `BOT_WEBHOOK_PATH=/webhook/telegram`;
- `BOT_WEBHOOK_SECRET=` или случайное секретное значение.

Генерация Fernet-ключа:

```bash
docker compose -f docker-compose.prod.yml run --rm api \
  python -c "from app.core.security import generate_encryption_key; print(generate_encryption_key())"
```

## Что делает `install.sh`

Скрипт:

- проверяет root/sudo;
- проверяет Ubuntu;
- устанавливает Git, Curl, Nginx, Certbot, DNS tools;
- устанавливает Docker Engine и Docker Compose plugin;
- создаёт пользователя `mpcontrol`;
- клонирует репозиторий в `/opt/mpcontrol`;
- если `/opt/mpcontrol` уже существует и принадлежит другому пользователю, аккуратно меняет
  владельца только для этой директории и добавляет путь в `git safe.directory`;
- создаёт `.env`, если его ещё нет;
- не перезаписывает существующий `.env`, но приводит владельца к `mpcontrol` и ставит `chmod 600`;
- проверяет обязательные env-переменные;
- настраивает Nginx;
- собирает production Docker images;
- запускает PostgreSQL и Redis;
- применяет Alembic migrations;
- запускает `api`, `bot`, `worker`;
- проверяет healthcheck;
- выпускает SSL-сертификаты через Certbot, если `SKIP_SSL` не включён.

Лог установки:

```bash
sudo tail -f /var/log/mpcontrol-install.log
```

## Проверка после установки

```bash
cd /opt/mpcontrol
docker compose -f docker-compose.prod.yml ps
curl http://127.0.0.1:8000/health
curl https://api.example.com/health
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f bot
docker compose -f docker-compose.prod.yml logs -f worker
```

В Telegram нажмите `/start`, затем `🌐 Web-кабинет`.

## Обновление

```bash
cd /opt/mpcontrol
sudo bash deploy/update.sh
```

`update.sh`:

- показывает текущую версию и commit;
- делает `git fetch`;
- выполняет `git pull --ff-only`;
- не трогает `.env`;
- предупреждает о новых переменных из `.env.example`;
- создаёт backup PostgreSQL через `deploy/backup.sh`;
- создаёт копию `.env` и metadata JSON backup;
- защищается от параллельных запусков через `runtime/update.lock`;
- сохраняет статус последнего deploy в `runtime/last_update_status.json`;
- пересобирает Docker images;
- **перед миграциями расширяет `alembic_version.version_num` до VARCHAR(128)** (идемпотентно);
- применяет миграции;
- перезапускает сервисы;
- проверяет healthcheck.

Лог обновления:

```bash
tail -f /opt/mpcontrol/logs/deploy/update.log
```

Если публичный healthcheck временно недоступен:

```bash
sudo SKIP_PUBLIC_HEALTH=1 bash deploy/update.sh
```

Если backup нужно временно пропустить:

```bash
sudo SKIP_BACKUP=1 bash deploy/update.sh
```

Режимы для CI/CD и диагностики:

```bash
sudo bash deploy/update.sh --check-only
sudo bash deploy/update.sh --non-interactive
```

`--check-only` делает `git fetch`, сравнивает текущий и удалённый commit и не меняет
рабочее дерево. `--non-interactive` пригоден для GitHub Actions и Telegram-админки.

## Резервные копии

Ручной backup:

```bash
cd /opt/mpcontrol
sudo bash deploy/backup.sh
```

Файлы сохраняются в:

```text
/opt/mpcontrol/backups/db/mpcontrol_YYYY-MM-DD_HH-MM-SS.sql.gz
/opt/mpcontrol/backups/env/.env_YYYY-MM-DD_HH-MM-SS.backup
/opt/mpcontrol/backups/meta/backup_YYYY-MM-DD_HH-MM-SS.json
```

Срок хранения задаётся переменной:

```text
BACKUP_RETENTION_DAYS=30
```

## GitHub Actions CI/CD

В проекте есть два workflow:

- `.github/workflows/ci.yml` — запускает ruff, black, mypy, pytest, Alembic upgrade и Docker build;
- `.github/workflows/deploy-production.yml` — после успешного CI на `main` или вручную через
  `workflow_dispatch` подключается к серверу по SSH и запускает
  `bash deploy/update.sh --non-interactive`.

Создайте GitHub Secrets:

```text
PROD_SSH_HOST=your.server.ip
PROD_SSH_PORT=22
PROD_SSH_USER=mpcontrol
PROD_SSH_PRIVATE_KEY=<private key>
PROD_PROJECT_DIR=/opt/mpcontrol
PROD_BRANCH=main
```

Публичный ключ для `PROD_SSH_PRIVATE_KEY` должен быть добавлен в
`/home/mpcontrol/.ssh/authorized_keys` на сервере. Пользователь должен иметь право запускать
Docker Compose и писать в `/opt/mpcontrol`.

## Telegram-админка обновлений

Для администраторов из `ADMIN_TELEGRAM_IDS` доступно:

```text
🛠 Администрирование → 🚀 Обновление и деплой
```

Раздел показывает текущую версию, проверку обновлений, статус последнего deploy, последние
строки `logs/deploy/update.log` и последние backup.

По умолчанию запуск обновления из Telegram отключён:

```text
ENABLE_TELEGRAM_DEPLOY_COMMANDS=false
```

Чтобы разрешить запуск обновления из Telegram, установите:

```text
ENABLE_TELEGRAM_DEPLOY_COMMANDS=true
TELEGRAM_DEPLOY_MODE=trigger
DEPLOY_UPDATE_COMMAND="bash deploy/update.sh --non-interactive"
DEPLOY_UPDATE_TRIGGER_FILE=/opt/mpcontrol/runtime/telegram_update_request.json
DEPLOY_METADATA_FILE=/opt/mpcontrol/runtime/deploy_metadata.json
```

Не добавляйте в `.env` отдельные исполняемые строки вроде `deploy/update.sh`.
Файл окружения должен содержать только `KEY=value`, комментарии через `#` и пустые
строки. Ручное обновление запускается отдельно:

```bash
bash deploy/update.sh
# или
chmod +x deploy/update.sh && ./deploy/update.sh
```

В production-режиме бот не выполняет произвольный shell внутри контейнера. Он создаёт
`runtime/telegram_update_request.json`, а host-side systemd watcher
`mpcontrol-telegram-update.path` запускает фиксированную команду:

```bash
cd /opt/mpcontrol
bash deploy/update.sh --non-interactive
```

`deploy/install.sh` устанавливает и включает:

```text
/etc/systemd/system/mpcontrol-telegram-update.path
/etc/systemd/system/mpcontrol-telegram-update.service
```

Параллельный запуск блокируется `runtime/update.lock`.

Проверка watcher:

```bash
sudo systemctl status mpcontrol-telegram-update.path
sudo systemctl status mpcontrol-telegram-update.service
```

После успешного update скрипт создаёт `runtime/deploy_metadata.json`. Этот файл читает
Telegram-бот, чтобы показывать версию, ветку, commit и сообщение последнего commit даже внутри
Docker-контейнера без `.git`.

Health-check в `deploy/update.sh` выполняется с ожиданием готовности API:

```text
HEALTHCHECK_RETRIES=20
HEALTHCHECK_INTERVAL_SECONDS=3
```

Это защищает deploy от ложной ошибки `Empty reply from server`, когда контейнер уже поднят,
но FastAPI ещё не успел начать отвечать на `/health`.

Перед `git pull` скрипт проверяет локальные изменения tracked-файлов. Если на сервере вручную
изменён файл из репозитория, update останавливается заранее, сохраняет diff в
`runtime/local_changes_YYYYMMDD_HHMMSS.diff` и пишет понятную ошибку в статус deploy. Это защищает
рабочую установку от тихого перетирания ручных правок.

## Nginx

Активная конфигурация:

```bash
/etc/nginx/sites-available/mpcontrol.conf
/etc/nginx/sites-enabled/mpcontrol.conf
/etc/nginx/sites-available/bot.mpcontrol.online.conf
/etc/nginx/sites-enabled/bot.mpcontrol.online.conf
```

Проверка:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Для домена Telegram webhook используйте отдельный config из репозитория. При первом
выпуске сертификата сначала поднимите временный HTTP-only server block для ACME:

```bash
sudo mkdir -p /var/www/certbot
sudo tee /etc/nginx/sites-available/bot.mpcontrol.online.http.conf >/dev/null <<'NGINX'
server {
    listen 80;
    server_name bot.mpcontrol.online;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 404;
    }
}
NGINX
sudo ln -sfn /etc/nginx/sites-available/bot.mpcontrol.online.http.conf /etc/nginx/sites-enabled/bot.mpcontrol.online.http.conf
sudo nginx -t
sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/certbot -d bot.mpcontrol.online
sudo cp deploy/nginx/bot.mpcontrol.online.conf /etc/nginx/sites-available/bot.mpcontrol.online.conf
sudo ln -sfn /etc/nginx/sites-available/bot.mpcontrol.online.conf /etc/nginx/sites-enabled/bot.mpcontrol.online.conf
sudo rm -f /etc/nginx/sites-enabled/bot.mpcontrol.online.http.conf
sudo nginx -t
sudo systemctl reload nginx
```

На `bot.mpcontrol.online` проксируются только:

```text
/webhook/telegram
/health
```

Web-кабинет `/web/` на этом домене должен возвращать 404.

Telegram webhook URL:

```text
https://bot.mpcontrol.online/webhook/telegram
```

Проверка:

```bash
cd /opt/mpcontrol
curl -I https://bot.mpcontrol.online/health
curl -I https://bot.mpcontrol.online/webhook/telegram
bash scripts/bot_get_webhook_info.sh
```

Если Telegram возвращает `Connection refused`, проверьте, что nginx на хосте
слушает 443 и включил конфиг bot-домена:

```bash
sudo nginx -t
sudo ss -tulpn | grep -E ':80|:443|:8000'
sudo grep -R "bot.mpcontrol.online" -n \
  /etc/nginx/sites-enabled /etc/nginx/conf.d /opt/mpcontrol/deploy/nginx 2>/dev/null
curl -4 -vkI https://bot.mpcontrol.online/health
curl -4 -vkI https://bot.mpcontrol.online/webhook/telegram
```

Для host-nginx upstream должен указывать на API-контейнер через
`127.0.0.1:8000`, потому что HTTP route `/webhook/telegram` обслуживает FastAPI,
а не bot-контейнер.

Для `app.example.com` путь проксируется в FastAPI без добавления лишнего `/web/`.
Ссылка из Telegram вида:

```text
https://app.example.com/web/login?token=...
```

должна попадать в backend route `/web/login`. Если после обновления кода всё ещё виден
`{"detail":"Not Found"}`, перегенерируйте Nginx-конфигурацию или вручную проверьте, что
`proxy_pass` для `app.example.com` равен:

```nginx
proxy_pass http://127.0.0.1:8000;
```

После успешной проверки токена backend отвечает редиректом на абсолютный путь `/web/`.
Канонический путь кабинета всегда начинается с одного `/web`.

Начиная с версии `1.4.18`, приложение дополнительно обслуживает legacy-пути вида
`/web/web/<раздел>`. Это страховка для серверов, где осталась старая reverse proxy-схема с
добавлением лишнего `/web` в upstream. Пользователь всё равно попадёт в авторизованный раздел,
а после обновления Nginx все ссылки останутся каноническими.

После входа создаётся полноценная web-сессия через cookie `seller_web_session` с `Path=/`.
Поэтому пользователь может переходить по разделам
`/web/profit`, `/web/orders`, `/web/sales`, `/web/returns`, `/web/products`, `/web/costs`
`/web/plan-fact`, `/web/break-even`, `/web/stocks`, `/web/alerts`, `/web/data-quality`
и `/web/settings` без повторной одноразовой ссылки из Telegram. В production cookie
помечается как `HttpOnly` и `Secure`.

## Firewall

Скрипт не включает UFW автоматически, чтобы не заблокировать SSH-доступ.

Рекомендуемые правила:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

## Частые ошибки

### DNS не настроен

Certbot не выпустит сертификаты. Проверьте:

```bash
dig +short example.com
dig +short app.example.com
dig +short api.example.com
dig +short bot.mpcontrol.online
```

### `.env` не заполнен

Скрипты остановятся и покажут список отсутствующих переменных. Исправьте:

```bash
sudo nano /opt/mpcontrol/.env
sudo bash /opt/mpcontrol/deploy/install.sh
```

### SSL не выдался

Проверьте DNS, открытые порты 80/443 и логи:

```bash
sudo certbot certificates
sudo tail -f /var/log/letsencrypt/letsencrypt.log
```

### Миграции не применились

```bash
cd /opt/mpcontrol
docker compose -f docker-compose.prod.yml run --rm api alembic current
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
```

Начиная с версии 1.8.1, `update.sh` автоматически расширяет колонку
`alembic_version.version_num` до `VARCHAR(128)` перед запуском миграций.
Это предотвращает ошибку `StringDataRightTruncationError` при длинных revision id.

Если нужно исправить вручную до обновления:

```bash
cd /opt/mpcontrol
source .env
docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128);"
```

### Бот не отвечает

```bash
cd /opt/mpcontrol
docker compose -f docker-compose.prod.yml logs --tail=200 bot
docker compose -f docker-compose.prod.yml logs --tail=200 worker
```

Проверьте `BOT_TOKEN`, доступность Telegram API и что не запущен второй экземпляр этого же бота.
