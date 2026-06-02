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
BOT_WEBHOOK_SECRET=
BOT_WEBHOOK_ENABLED=false
```

FastAPI route находится в `app/api/telegram_webhook.py`: `POST /webhook/telegram`.
Если `BOT_WEBHOOK_SECRET` задан, endpoint проверяет заголовок
`X-Telegram-Bot-Api-Secret-Token`.

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

Проверка домена:

```bash
curl -I https://bot.mpcontrol.online/health
curl -I https://bot.mpcontrol.online/webhook/telegram
```

Для `GET /webhook/telegram` допустимы `403` от nginx `limit_except` или `405` от FastAPI,
поскольку Telegram отправляет webhook через POST.

## YooKassa

Канонический YooKassa webhook остаётся на домене web-кабинета:

```text
https://app.mpcontrol.online/webhooks/yookassa
```
