# version: 1.1.0
# description: Production diagnostics checklist for WEB routes, migrations, and FBS notifications.
# updated: 2026-05-17

# Production Debug Checklist

## WEB 500

Проверить актуальность кода и контейнеров:

```bash
git rev-parse HEAD
git status --short
docker compose ps
docker compose logs --tail=300 api
```

Проверить миграции:

```bash
docker compose exec api alembic current
docker compose exec api alembic heads
docker compose exec api alembic upgrade head
```

Критичные production-fix миграции:

- `20260517_0013_subscription_lifecycle` — добавляет `user_subscriptions.period`;
- `20260517_0014_ensure_payment_metadata_column` — досоздаёт `payments.payment_metadata`,
  если production-БД применяла ранний вариант платежной миграции без этой колонки.

## WEB Login Flow

```bash
curl -i https://mpcontrol.online/web/
curl -i "https://mpcontrol.online/web/login?token=PASTE_REAL_TOKEN"
```

Ожидается:

- `/web/login?token=...` возвращает `303` на `/web/`;
- в ответе есть `Set-Cookie`;
- `/web/`, `/web/profit`, `/web/analytics` открываются без 500 после cookie.

## Double WEB Prefix

Штатная навигация должна использовать только canonical URLs:

- `/web/settings`
- `/web/profile`
- `/web/subscription`
- `/web/accounts`
- `/web/orders`
- `/web/sales`
- `/web/returns`
- `/web/profit`
- `/web/products`
- `/web/product-matching`
- `/web/analytics`

Если в логах остаётся `legacy_double_web_path` для `/web/web/*`, проверить:

```bash
docker compose exec api env | grep -E "WEB_BASE_URL|APP_BASE_URL"
docker compose logs --tail=300 api | grep legacy_double_web_path
```

Новая версия нормализует Telegram login link до `/web/login?token=...`. Compatibility-route
`/web/web/*` сохранён только для старых ссылок и reverse proxy.

## Profit / Analytics GroupingError

Если снова появляется:

```text
asyncpg.exceptions.GroupingError:
column "order_items.title" must appear in the GROUP BY clause
```

Проверить, что на сервере установлен commit с исправлением
`WebOrdersProfitService._profit_order_query()`, где `title_expr` и `article_expr` используются
одновременно в `SELECT` и `GROUP BY`.

## FBS Notifications

```bash
docker compose logs -f worker | grep -E "order_notification_prepared|unnotified_order_notification_retried|new_order_notification_sent|new_order_notification_send_failed"
```

Новый FBS-заказ должен пройти цепочку:

1. `order_persisted`
2. `order_notification_prepared`
3. `new_order_notification_sent`

Если отправка упала, заказ не помечается отправленным и должен повториться на следующем polling.
