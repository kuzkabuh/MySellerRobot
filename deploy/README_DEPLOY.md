# version: 1.0.0
# description: Production deployment guide for MP Control on Ubuntu VPS.
# updated: 2026-05-15

# Production-развёртывание MP Control

Эта инструкция описывает первый запуск и обновление MP Control на VPS с Ubuntu 22.04 LTS
или Ubuntu 24.04 LTS.

## Архитектура

- Приложение запускается через Docker Compose production stack:
  `postgres`, `redis`, `api`, `bot`, `worker`.
- Nginx и Certbot устанавливаются на хосте.
- Telegram-бот сейчас работает через long polling. Домен `bot.mpcontrol.online` зарезервирован
  для будущего webhook-сценария.
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

- `https://mpcontrol.online` — публичная заглушка/лендинг;
- `https://www.mpcontrol.online` — alias лендинга;
- `https://app.mpcontrol.online` — web-кабинет;
- `https://api.mpcontrol.online` — backend API;
- `https://bot.mpcontrol.online` — резерв под Telegram webhook.

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
  SSL_EMAIL="owner@mpcontrol.online" \
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
- `WEB_BASE_URL=https://app.mpcontrol.online`;
- `WEB_APP_BASE_URL=https://app.mpcontrol.online`;
- `API_BASE_URL=https://api.mpcontrol.online`;
- `PUBLIC_SITE_URL=https://mpcontrol.online`.

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
- создаёт `.env`, если его ещё нет;
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
curl https://api.mpcontrol.online/health
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
- пересобирает Docker images;
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

## Резервные копии

Ручной backup:

```bash
cd /opt/mpcontrol
sudo bash deploy/backup.sh
```

Файлы сохраняются в:

```text
/opt/mpcontrol/backups/mpcontrol_YYYY-MM-DD_HH-MM-SS.sql.gz
```

## Nginx

Активная конфигурация:

```bash
/etc/nginx/sites-available/mpcontrol.conf
/etc/nginx/sites-enabled/mpcontrol.conf
```

Проверка:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

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
dig +short mpcontrol.online
dig +short app.mpcontrol.online
dig +short api.mpcontrol.online
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

### Бот не отвечает

```bash
cd /opt/mpcontrol
docker compose -f docker-compose.prod.yml logs --tail=200 bot
docker compose -f docker-compose.prod.yml logs --tail=200 worker
```

Проверьте `BOT_TOKEN`, доступность Telegram API и что не запущен второй экземпляр этого же бота.
