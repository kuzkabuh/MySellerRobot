# version: 1.0.0
# description: Production diagnostics checklist for WEB 500 errors and FBS notifications.
# updated: 2026-05-17

# Production Debug Checklist

Этот чеклист нужен для быстрой диагностики двух критичных сценариев:

- WEB-ссылка из Telegram открывает `/web/login?token=...`, но сервер возвращает `Internal Server Error`;
- новые FBS-заказы WB/Ozon сохраняются или приходят из API, но пользователь не получает Telegram-уведомление.

## 1. Версия кода

```bash
git rev-parse HEAD
git status --short
cat VERSION
git log --oneline -5
```

Важно: контейнеры должны быть собраны из того же commit, который виден в `git rev-parse HEAD`.

## 2. Контейнеры и логи

```bash
docker compose ps
docker compose logs --tail=200 api
docker compose logs --tail=200 bot
docker compose logs --tail=200 worker
```

Для live-диагностики:

```bash
docker compose logs -f api
docker compose logs -f worker
```

## 3. Миграции БД

```bash
docker compose exec api alembic current
docker compose exec api alembic heads
docker compose exec api alembic upgrade head
docker compose exec api alembic current
```

Критично для текущей версии: должна быть применена миграция
`20260517_0013_subscription_lifecycle`. Если её нет, WEB может падать на production из-за
отсутствующей колонки `user_subscriptions.period` при чтении подписки.

Также должна быть применена корректирующая миграция
`20260517_0014_ensure_payment_metadata_column`. Она досоздаёт `payments.payment_metadata`, если
production-БД применяла ранний вариант платежной миграции без этой колонки.

## 4. Проверка WEB

```bash
curl -i https://mpcontrol.online/web/
curl -i "https://mpcontrol.online/web/login?token=PASTE_REAL_ONE_TIME_TOKEN"
```

Что проверить:

- `/web/` без cookie должен вернуть понятную ошибку авторизации, не traceback;
- `/web/login?token=...` должен вернуть redirect на `/web/`;
- в ответе `/web/login` должен быть `Set-Cookie`;
- после redirect главная страница должна открыться с `200`.

Если снова виден 500:

```bash
docker compose logs --tail=300 api | grep -E "request_failed|Internal Server Error|Traceback|UndefinedColumn|MissingGreenlet|AttributeError|KeyError"
```

## 5. Проверка конфигурации WEB

```bash
docker compose exec api env | grep -E "WEB_BASE_URL|APP_BASE_URL|SESSION|COOKIE|ADMIN|DATABASE_URL"
```

Проверьте:

- `WEB_BASE_URL` указывает на реальный публичный домен;
- `WEB_BASE_URL` не должен содержать двойной web-prefix. Допустимо `https://mpcontrol.online`
  или `https://mpcontrol.online/web`, но новая версия всё равно нормализует ссылку до
  `/web/login?token=...`;
- reverse proxy прокидывает `Set-Cookie` и redirect без переписывания path;
- production-контейнеры перезапущены после обновления образа;
- `.env` не содержит старых доменов или несовместимых cookie-настроек.

## 6. Проверка FBS-уведомлений

Запустите worker-логи и дождитесь нового FBS-заказа или ручного polling:

```bash
docker compose logs -f worker | grep -E "order_poll_started|order_persisted|order_notification_prepared|unnotified_order_notification_retried|new_order_notification_sent|new_order_notification_send_failed"
```

Ожидаемая цепочка для нового FBS-заказа:

1. `order_poll_started`
2. `order_persisted`
3. `order_notification_prepared`
4. `new_order_notification_sent`

Если отправка упала, должен быть `new_order_notification_send_failed`. Заказ не будет помечен
как отправленный, и следующий polling должен дать `unnotified_order_notification_retried`.

## 7. Проверка данных FBS-заказа в БД

```bash
docker compose exec db psql "$POSTGRES_DB" -c "
select id, user_id, marketplace, sale_model, fulfillment_type, order_external_id,
       first_notified_at, last_notified_at, created_at
from orders
where sale_model in ('FBS', 'rFBS', 'DBS', 'DBW')
order by created_at desc
limit 20;"
```

Если `first_notified_at` пустой у свежего FBS-заказа, смотрите worker-логи по `order_id`:

```bash
docker compose logs --tail=500 worker | grep "ORDER_ID_HERE"
```

## 8. Smoke-проверки после деплоя

```bash
docker compose exec api python -c "import app.api.main; print('API OK')"
docker compose exec bot python -c "import app.bot.main; print('BOT OK')"
docker compose exec api python -c "from app.api.main import create_app; app = create_app(); print(app.version)"
docker compose exec api pytest tests/integration/test_api_smoke.py::test_web_login_token_flow_renders_empty_free_dashboard -q
docker compose exec api pytest tests/unit/test_fbs_order_notification_retries.py -q
```

## 9. Что прислать для повторной диагностики

- commit hash: `git rev-parse HEAD`;
- вывод `alembic current` и `alembic heads`;
- последние 300 строк `api` и `worker` логов;
- если ошибка содержит `payments.payment_metadata`, вывод
  `docker compose exec api alembic current` после `alembic upgrade head`;
- URL без токена или с замаскированным токеном;
- время попытки входа в WEB;
- `order_id` / `order_external_id` FBS-заказа, по которому не пришло уведомление.
