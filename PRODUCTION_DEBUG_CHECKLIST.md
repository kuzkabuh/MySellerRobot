# version: 1.3.0
# description: Production diagnostics checklist for WEB URLs, migrations, FBS orders, and notifications.
# updated: 2026-05-17

# Production Debug Checklist

## Deploy

```bash
git rev-parse HEAD
git status --short
docker compose build api bot worker
docker compose up -d api bot worker
docker compose exec api alembic upgrade head
docker compose logs --tail=300 api
```

Критичные миграции:

- `20260517_0013_subscription_lifecycle`
- `20260517_0014_ensure_payment_metadata_column`
- `20260517_0015_subscription_timestamp_defaults`

## WEB Canonical URLs

Штатная навигация должна использовать только `/web/*`.

Проверить в логах:

```bash
docker compose logs --tail=300 api | grep legacy_double_web_path
```

Если `legacy_double_web_path` появляется после деплоя, убедиться, что пользователь не находится
на старой открытой вкладке `/web/web/*`. Новая версия должна редиректить legacy GET:

```bash
curl -i https://mpcontrol.online/web/web/profit
curl -i https://mpcontrol.online/web/web/costs/97
```

Ожидается `308` на canonical URL:

- `/web/profit`
- `/web/costs/97`

## Cost Save

Canonical save:

```bash
POST /web/costs/{product_id}
```

Temporary legacy compatibility save:

```bash
POST /web/web/costs/{product_id}
```

Оба должны возвращать `303` на:

```text
/web/costs/{product_id}?saved=1
```

## Profit / Analytics

Если снова появляется PostgreSQL `GroupingError`, проверить, что сервер содержит исправление
`WebOrdersProfitService._profit_order_query()` с переиспользованием `title_expr` и `article_expr`
в `SELECT` и `GROUP BY`.

## FBS Notifications

```bash
docker compose logs -f worker | grep -E "fbs_order_|order_notification_prepared|unnotified_order_notification_retried|new_order_notification_sent|new_order_notification_send_failed"
```

Новый FBS-заказ должен пройти цепочку:

1. `fbs_order_polled`
2. `fbs_order_normalized`
3. `fbs_order_detected_as_new`
4. `fbs_order_persisted`
5. `fbs_order_notification_prepared`
6. `fbs_order_notification_sent`

Если Telegram-отправка упала, `first_notified_at` не заполняется, а следующий polling должен
показать `fbs_order_duplicate_with_unsent_notification_requeued`.
