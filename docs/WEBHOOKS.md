# Webhooks

## Telegram Bot API

Telegram webhook использует отдельный домен:

```text
https://bot.mpcontrol.online
```

Полный URL:

```text
https://bot.mpcontrol.online/webhook/telegram
```

Настройки в `.env`:

```env
BOT_WEBHOOK_BASE_URL=https://bot.mpcontrol.online
BOT_WEBHOOK_PATH=/webhook/telegram
BOT_WEBHOOK_SECRET=change-me
TELEGRAM_WEBHOOK_SECRET=
BOT_WEBHOOK_ENABLED=false
WEBHOOK_ALLOW_INSECURE_DEV=0
```

FastAPI route находится в `app/api/telegram_webhook.py`: `POST /webhook/telegram`.
В production `BOT_WEBHOOK_SECRET` обязателен: endpoint проверяет заголовок
`X-Telegram-Bot-Api-Secret-Token` и отклоняет запрос, если секрет не настроен или неверен.
Для локальной отладки без секрета нужно явно задать `WEBHOOK_ALLOW_INSECURE_DEV=1`;
в production этот режим не включается.

Nginx config для отдельного домена: `deploy/nginx/bot.mpcontrol.online.conf`.
На `bot.mpcontrol.online` должны быть доступны только `/webhook/telegram` и `/health`;
web-кабинет `/web/` должен возвращать 404.

Первый выпуск SSL:

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

Проверка URL из `.env`:

```bash
cd /opt/mpcontrol
set -a
source .env
set +a

echo "${BOT_WEBHOOK_BASE_URL%/}${BOT_WEBHOOK_PATH}"
```

Установка webhook:

```bash
bash scripts/bot_set_webhook.sh
```

Проверка Telegram webhook:

```bash
curl -sS "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo"
```

В ответе Telegram `result.url` должен быть:

```text
https://bot.mpcontrol.online/webhook/telegram
```

### Диагностика `Connection refused`

Если Telegram показывает `last_error_message: Connection refused`, запрос обычно
не дошёл до FastAPI. Рабочая цепочка:

```text
Telegram -> bot.mpcontrol.online:443 -> nginx -> 127.0.0.1:8000 -> FastAPI /webhook/telegram -> aiogram dispatcher
```

Проверьте на сервере:

```bash
cd /opt/mpcontrol

docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=200 bot
docker compose -f docker-compose.prod.yml logs --tail=200 api

sudo nginx -t
sudo ss -tulpn | grep -E ':80|:443|:8000'
sudo grep -R "bot.mpcontrol.online" -n \
  /etc/nginx/sites-enabled /etc/nginx/conf.d /opt/mpcontrol/deploy/nginx 2>/dev/null

curl -4 -vkI https://bot.mpcontrol.online/health
curl -4 -vkI https://bot.mpcontrol.online/webhook/telegram

set -a
source .env
set +a
curl -s "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo" | python3 -m json.tool
```

`bot.mpcontrol.online.conf` должен быть включён в nginx и проксировать
`/webhook/telegram` в API на `http://127.0.0.1:8000/webhook/telegram`.
Если nginx проксирует в bot-контейнер, webhook не будет обработан: HTTP route
живёт в API-контейнере.

Проверка домена:

```bash
curl -I https://bot.mpcontrol.online/health
curl -I https://bot.mpcontrol.online/webhook/telegram
```

Для `GET /webhook/telegram` допустимы `403` от nginx `limit_except` или `405` от FastAPI,
поскольку Telegram отправляет webhook через POST.

Переустановка webhook с secret:

```bash
curl -s "https://api.telegram.org/bot${BOT_TOKEN}/deleteWebhook?drop_pending_updates=false" \
  | python3 -m json.tool

curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
  -d "url=https://bot.mpcontrol.online/webhook/telegram" \
  -d "secret_token=${BOT_WEBHOOK_SECRET:-${TELEGRAM_WEBHOOK_SECRET}}" \
  -d "drop_pending_updates=false" \
  -d 'allowed_updates=["message","callback_query"]' \
  | python3 -m json.tool
```

Без secret это допустимо только для локальной отладки при
`WEBHOOK_ALLOW_INSECURE_DEV=1`; production должен использовать secret.

## YooKassa

Канонический YooKassa webhook остаётся на домене web-кабинета:

```text
https://app.mpcontrol.online/webhooks/yookassa
```

Настройки:

```env
YOOKASSA_WEBHOOK_URL=https://app.mpcontrol.online/webhooks/yookassa
YOOKASSA_WEBHOOK_SECRET=<shared-secret>
```

В production `YOOKASSA_WEBHOOK_SECRET` обязателен. Секрет принимается только через
header `x-yookassa-webhook-secret`; query-параметр `secret` не используется.
