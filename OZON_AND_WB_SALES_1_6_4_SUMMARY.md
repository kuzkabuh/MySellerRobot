# Ozon integration и WB daily sales report — релиз 1.6.4

## Что подтверждено аудитом

### Ozon API

- `POST /v3/product/list` используется в `ProductSyncService` и поддерживает `last_id`.
- `POST /v3/product/info/list` используется для обогащения карточек Ozon.
- `POST /v4/product/info/stocks` использовался, но доработан: добавлена cursor-пагинация.
- `POST /v1/product/info/stocks-by-warehouse/fbs` был в клиенте, но не использовался в продукте.
- `POST /v5/product/info/prices`, `POST /v2/warehouse/list`, SellerInfo и promo-методы были только
  клиентским фундаментом без бизнес-сценариев.
- `POST /v3/posting/fbs/list` и `POST /v3/posting/fbs/unfulfilled/list` используются для FBS-заказов
  и объединяются без дублей.
- `POST /v3/posting/fbs/get` остаётся точечным методом для будущего on-demand обогащения деталей,
  чтобы не создавать лишние N+1 запросы к Ozon.

## Что реализовано

- SellerInfo сохраняется в `marketplace_accounts`:
  - `seller_external_id`;
  - `seller_name`;
  - `seller_legal_name`;
  - `seller_info_payload`.
- Добавлен справочник складов `marketplace_warehouses`.
- Добавлены снимки цен Ozon `ozon_price_snapshots`.
- Добавлены акции Ozon `ozon_promos` и `ozon_promo_products`.
- Добавлен `OzonCatalogEnrichmentService`:
  - синхронизация складов;
  - синхронизация цен с cursor-пагинацией;
  - синхронизация акций и товаров в акциях.
- `StockService` теперь:
  - загружает все страницы Ozon stock API;
  - дополнительно сохраняет FBS-остатки по складам;
  - не ограничивается первыми 1000 строками.
- Ozon polling теперь использует `last_order_poll_at` и overlap 10 минут.
  При ошибке polling метка не обновляется, поэтому следующий запуск не теряет окно.

## WB daily sales report

Добавлена ежедневная задача `sync_wb_daily_sales_reports`.

Расписание:

- 05:00 МСК;
- в worker это настроено как 02:00 UTC.

Каждый запуск загружает:

- D-1 — основной день;
- D-2 — актуализация предварительных сумм;
- D-3 — дополнительная корректировка.

Используется метод:

```text
GET /api/v1/supplier/sales?dateFrom=YYYY-MM-DD&flag=1
```

Строки сохраняются идемпотентно:

- продажи идут в `sales_events`;
- возвраты идут в `returns_events`;
- повторный импорт обновляет суммы и payload, а не создаёт дубль.

Важно: эти данные используются как оперативная аналитика продаж и возвратов. Они не подменяют
точный финансовый отчёт реализации WB.

## Миграции

- `20260517_0017_ozon_enrichment_and_account_seller.py`

## Тесты

Добавлены/обновлены проверки:

- SellerInfo normalization;
- Ozon cursor stocks;
- Ozon prices, warehouses, actions/promos;
- WB supplier sales `flag=1`;
- WB return detection and normalization;
- Ozon enrichment parsing helpers.

Финальная проверка 17.05.2026:

- `python -c "import app.api.main; print('API OK')"` — OK;
- `python -c "import app.bot.main; print('BOT OK')"` — OK;
- `python -c "import app.workers.settings; print('WORKER OK')"` — OK;
- `python -m pytest -q` — 244 passed;
- `python -m ruff check .` — OK;
- `python -m ruff format --check .` — OK;
- `python -m mypy app` — OK.
- `docker compose config --quiet` — OK;
- `python -m alembic heads` — head `20260517_0017`.

После повышения версии тесты smoke/API обновлены с `1.6.3` на `1.6.4`.
WEB-форма себестоимости дополнительно защищена: если в тестовом или старом DTO нет
`latest_ozon_price`, страница не падает и показывает аккуратное состояние без цены.

`alembic history -r -3:current` в локальной среде требует подключения к БД и не был завершён:
текущий `DATABASE_URL` не резолвится из этой машины. Проверка head без подключения к БД проходит.

## Production notes

После деплоя обязательно выполнить:

```bash
alembic upgrade head
```

Новые миграции добавляют поля seller-info, `last_order_poll_at`, справочник складов,
снимки цен Ozon и таблицы акций. Без миграций worker-сценарии Ozon enrichment и WEB-блоки
кабинетов/цен не смогут корректно работать на production-БД.

## Ограничения

- Детальный `PostingAPI_GetFbsPosting` не вызывается массово, чтобы не перегружать API.
  Его следует использовать on-demand для карточек деталей.
- Promo API сохраняет только read-only поля, реально полученные от Ozon.
- WB supplier/sales остаётся предварительным источником. Точный P&L должен строиться по отчёту
  реализации, когда он будет полностью интегрирован.
