# version: 1.2.0
# description: Production diagnostics checklist for WEB canonical URLs, migrations, and notifications.
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
docker compose logs -f worker | grep -E "order_notification_prepared|unnotified_order_notification_retried|new_order_notification_sent|new_order_notification_send_failed"
```
