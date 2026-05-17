# version: 1.2.0
# description: Critical production fixes report for WEB canonical URLs, costs, profit analytics, and schema drift.
# updated: 2026-05-17

# Refactoring and Critical Fixes Report

## WEB Profit / Analytics GroupingError

Production падал на `/web/profit` и `/web/analytics` с:

```text
asyncpg.exceptions.GroupingError:
column "order_items.title" must appear in the GROUP BY clause
```

Причина была в `WebOrdersProfitService._profit_order_rows()`: выражения для названия товара и
артикула создавались отдельно в `SELECT` и отдельно в `GROUP BY`. SQLAlchemy генерировал разные
bind-параметры, а PostgreSQL не считал выражения эквивалентными.

Исправление:

- добавлен builder `WebOrdersProfitService._profit_order_query()`;
- `title_expr` и `article_expr` создаются один раз;
- эти же expression objects используются в `SELECT` и `GROUP BY`;
- fallback-строки переведены на `literal_column`;
- `_sales_by_sku()` также использует единый `article_expr`.

## WEB Canonical URL Fix

Production продолжал логировать `legacy_double_web_path` для `/web/web/*`, а сохранение
себестоимости падало:

```text
GET /web/web/costs/97 -> 200
POST /web/web/costs/97 -> 405
```

Canonical HTML-форма редактирования себестоимости формируется как:

```html
<form method="post" action="/web/costs/{id}">
```

Но старая открытая вкладка, старый URL или reverse proxy rewrite могли удерживать пользователя на
legacy path `/web/web/costs/{id}`. Для него существовал только GET compatibility handler, поэтому
POST возвращал 405.

Исправление:

- legacy GET `/web/web/{section}` теперь делает `308` redirect на canonical `/web/{section}`;
- query string сохраняется;
- добавлен temporary compatibility POST `/web/web/costs/{product_id}`;
- legacy POST вызывает canonical `save_product_cost()` и возвращает redirect
  `/web/costs/{id}?saved=1`;
- штатная навигация и формы покрыты тестами на отсутствие `href="/web/web/..."`
  и `action="/web/web/..."`.

Compatibility-route оставлен, но теперь он выталкивает браузер на canonical URL вместо рендера
страниц внутри `/web/web/*`.

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
- `/web/settings`, `/web/costs`, `/web/costs/{id}` не содержат `/web/web/`;
- форма себестоимости использует `action="/web/costs/{id}"`;
- canonical `POST /web/costs/{id}` сохраняет данные;
- legacy `POST /web/web/costs/{id}` сохраняет данные и редиректит на canonical URL.

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
