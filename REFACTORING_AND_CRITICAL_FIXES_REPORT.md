# version: 1.1.0
# description: Critical production fixes report for WEB profit analytics, navigation, and schema drift.
# updated: 2026-05-17

# Refactoring and Critical Fixes Report

## WEB Profit / Analytics 500

Production traceback:

```text
asyncpg.exceptions.GroupingError:
column "order_items.title" must appear in the GROUP BY clause
or be used in an aggregate function
```

Падали страницы:

- `/web/profit`
- `/web/analytics`
- legacy compatibility paths `/web/web/profit` и `/web/web/analytics`

## Root Cause

В `app/services/web_orders_profit_service.py` метод `_profit_order_rows()` строил выражения
названия товара и артикула отдельно в `SELECT` и отдельно в `GROUP BY`:

- `coalesce(order_items.title, order_items.seller_article, :fallback_title)`
- `coalesce(order_items.seller_article, :fallback_article)`

SQLAlchemy создавал разные bind-параметры для одинаковых fallback-строк в `SELECT` и `GROUP BY`.
PostgreSQL не считал такие выражения эквивалентными и выбрасывал `GroupingError`.

## Fix

В `WebOrdersProfitService` добавлен отдельный builder query:

- `_profit_order_query(user_id, filters)`

В нём используются одни и те же SQLAlchemy expression objects:

- `title_expr`
- `article_expr`

Эти выражения переиспользуются:

- в `SELECT`;
- в `GROUP BY`;
- в regression-тесте компилируются PostgreSQL dialect.

Fallback-строки переведены на SQL literals через `literal_column`, чтобы в SQL не появлялись
разные bind-параметры для одного и того же выражения.

Дополнительно аналогично исправлен `article_expr` в `_sales_by_sku()`.

## Double `/web/web/*`

Повторный аудит показал, что штатная web-навигация в `app/web/rendering.py` уже использует
канонические абсолютные ссылки `/web/*`.

Проверено тестом:

- HTML главной web-оболочки не содержит `/web/web`;
- `/web/profit` и `/web/analytics` возвращают 200 в smoke-тесте;
- compatibility-route `/web/web/*` сохранён только для старых ссылок и reverse proxy.

Если production продолжает логировать `legacy_double_web_path`, источник находится вне нового
HTML renderer: старая открытая вкладка, старый Telegram URL, reverse proxy rewrite или старое
значение `WEB_BASE_URL`. Новая генерация Telegram login link нормализует base URL до
`/web/login?token=...`.

## Ранее закрытые critical fixes

- `/start` и `/menu` обрабатываются глобальным `navigation` router и очищают активный FSM state;
- `payments.payment_metadata` досоздаётся production-safe миграцией
  `20260517_0014_ensure_payment_metadata_column`;
- FBS-уведомления помечают заказ отправленным только после успешной Telegram-доставки.

## Tests

Добавлены/обновлены проверки:

- PostgreSQL-compatible SQL для `profit_by_sku`;
- `/web/profit` возвращает 200;
- `/web/analytics` возвращает 200;
- web navigation не содержит `/web/web/`;
- login redirect остаётся `/web/`.

## Server Commands

```bash
git pull
docker compose build api bot worker
docker compose up -d api bot worker
docker compose exec api alembic upgrade head
docker compose exec api python -c "import app.api.main; print('API OK')"
docker compose exec bot python -c "import app.bot.main; print('BOT OK')"
docker compose logs --tail=300 api
```
