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

## Ограничения

- Детальный `PostingAPI_GetFbsPosting` не вызывается массово, чтобы не перегружать API.
  Его следует использовать on-demand для карточек деталей.
- Promo API сохраняет только read-only поля, реально полученные от Ozon.
- WB supplier/sales остаётся предварительным источником. Точный P&L должен строиться по отчёту
  реализации, когда он будет полностью интегрирован.
