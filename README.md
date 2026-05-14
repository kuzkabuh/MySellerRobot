# version: 1.0.0
# description: Product architecture, setup, API notes, and MVP status.
# updated: 2026-05-14

# Seller Profit Bot / KUZ’KA.SELLER BOT

Telegram-бот для селлеров Wildberries и Ozon. Главная идея продукта: бот сообщает не только о новом заказе, а сразу показывает плановую прибыль или убыток по нему.

## Статус реализации

Реализован Этап 1 и заложены основы следующих этапов:

- production-каркас Python 3.12, FastAPI, aiogram 3, SQLAlchemy 2, Alembic, PostgreSQL, Redis, arq;
- полная базовая схема БД из требований;
- Docker Compose, Makefile, `.env.example`;
- тонкие Telegram handlers: `/start`, `/help`, `/summary`, `/orders`, `/profit`, `/stocks`, `/alerts`, `/settings`;
- клиенты Wildberries и Ozon с нормализацией заказов;
- сервисы прибыли, алертов, форматирования сообщений, Excel-импорта себестоимости;
- миграция Alembic `20260514_0001_initial_schema`;
- unit/integration/smoke тесты для ключевой бизнес-логики.

Реализован Этап 2:

- пошаговое подключение Wildberries через Telegram FSM;
- пошаговое подключение Ozon через Telegram FSM;
- проверка WB API key через `GET https://common-api.wildberries.ru/ping`;
- проверка Ozon Client ID + API key через безопасный read-only `POST /v3/product/list`;
- шифрование API-ключей и Ozon Client ID через Fernet;
- список кабинетов пользователя;
- удаление кабинета пользователем через soft-disable;
- RedisStorage для состояний aiogram;
- `/cancel` для отмены сценария подключения.

Реализован Этап 3:

- синхронизация товаров Wildberries через `POST /content/v2/get/cards/list`;
- синхронизация товаров Ozon через `POST /v3/product/list`;
- upsert товаров в `products` с внешними идентификаторами, артикулами, названием, брендом, категорией и изображением;
- история себестоимости через `product_cost_history`;
- ручной ввод себестоимости в Telegram;
- скачивание Excel-шаблона себестоимости;
- загрузка Excel-файла с валидацией колонок, размером до 5 МБ и отчётом по ошибкам;
- закрытие предыдущего периода себестоимости при добавлении новой цены с даты;
- тесты нормализации товаров и ручного парсинга себестоимости.

Реализованы MVP-части Этапов 4-8:

- polling новых заказов WB/Ozon вынесен в `OrderProcessingService`;
- новые заказы сохраняются идемпотентно и получают плановый `ProfitSnapshot`;
- позиции заказа связываются с локальными товарами по артикулам/внешним ID;
- расчёт плановой прибыли использует себестоимость, действующую на дату заказа;
- worker отправляет карточку нового заказа в Telegram;
- ежедневный отчёт строится из заказов и плановой прибыли;
- разделы `📊 Сводка`, `💰 Прибыль`, `📦 Остатки`, `⚠ Контроль` читают данные из БД;
- FBS-контроль создаёт idempotent `AlertEvent` по риску дедлайна;
- синхронизация остатков WB/Ozon сохраняет `stock_snapshots`;
- низкие остатки создают `AlertEvent`;
- добавлен `FinanceService` для нормализованных финансовых строк и фактических `ProfitSnapshot`;
- ARQ cron-задачи настроены для polling заказов, ежедневных отчётов, FBS-контроля и остатков.

## Почему arq

Для фоновых задач выбран `arq`, потому что проект асинхронный: aiogram, FastAPI, httpx и клиенты маркетплейсов работают через async I/O. `arq` использует Redis, проще Celery для async-кода, поддерживает retries/job timeout и хорошо подходит для polling-задач: новые заказы, остатки, FBS-дедлайны, ежедневные отчёты. Celery мощнее для сложных distributed workflow, но в этом MVP дал бы больше инфраструктурной тяжести и синхронных обёрток.

## Проверенные официальные API

Проверено 14.05.2026 по официальным страницам WB API и Ozon Help/Seller API.

### Wildberries

Базовые домены:

- `https://marketplace-api.wildberries.ru` — FBS-заказы и поставки;
- `https://content-api.wildberries.ru` — карточки товаров;
- `https://seller-analytics-api.wildberries.ru` — аналитика и остатки;
- `https://finance-api.wildberries.ru` — финансовые отчёты.

Использованные/заложенные методы:

- `GET /api/v3/orders/new` — новые FBS сборочные задания;
- `GET /api/v3/orders` — список сборочных заданий за период;
- `POST /api/v3/orders/status` — статусы сборочных заданий;
- `POST /api/marketplace/v3/orders/meta` — метаданные сборочных заданий;
- `GET /api/v3/supplies`, `PATCH /api/v3/supplies/{supplyId}/deliver` — контроль поставок FBS;
- `POST /content/v2/get/cards/list` — карточки товаров;
- `POST /api/analytics/v1/stocks-report/wb-warehouses` — актуальный метод остатков WB-складов, заменяет старый `GET /api/v1/supplier/stocks`, который объявлен к отключению 23.06.2026;
- `POST /api/finance/v1/sales-reports/list`;
- `POST /api/finance/v1/sales-reports/detailed`;
- `POST /api/finance/v1/sales-reports/detailed/{reportId}`;
- `POST /api/finance/v1/acquiring/list`;
- `POST /api/finance/v1/acquiring/detailed`;
- `POST /api/finance/v1/acquiring/detailed/{reportId}`.

Важно: новый WB finance v1 sales reports появился в апреле 2026. Старый `GET /api/v5/supplier/reportDetailByPeriod` отмечен как текущий, но объявлен к отключению 15.07.2026, поэтому новая архитектура не завязана на него.

### Ozon

Базовый домен:

- `https://api-seller.ozon.ru`

Использованные/заложенные методы:

- `POST /v3/posting/fbs/list` — список FBS отправлений;
- `POST /v3/posting/fbs/get` — детализация FBS отправления;
- `POST /v3/posting/fbs/unfulfilled/list` — неотгруженные отправления для FBS-контроля;
- `POST /v3/product/list` — список товаров;
- `POST /v4/product/info/stocks` — остатки товаров;
- `POST /v1/product/info/stocks-by-warehouse/fbs` — остатки FBS/rFBS по складам;
- `POST /v1/returns/list` — возвраты;
- `POST /v1/report` и `POST /v1/report/info` — отчётная архитектура для финансовых/складских отчётов.

Важно: старые финансовые методы `POST /v3/finance/transaction/list` и `POST /v3/finance/transaction/totals` не используются как основа, потому что заявлены к отключению 06.07.2026. Для временной совместимости можно добавить `LegacyOzonFinanceAdapter`, но бизнес-логика уже работает через нормализованные `financial_report_rows`.

## Архитектура

```text
app/
  api/                 FastAPI health/admin endpoints
  bot/                 aiogram startup, handlers, keyboards
  core/                settings, db, security, logging
  integrations/        WB/Ozon async API clients
  models/              SQLAlchemy models and enums
  repositories/        persistence/idempotency helpers
  schemas/             Pydantic DTO
  services/            profit, alerts, reports, notifications, Excel
  workers/             arq background tasks
migrations/            Alembic
tests/                 unit, integration, smoke
```

Правило слоёв: Telegram handlers не считают прибыль и не ходят напрямую в API маркетплейсов. Они вызывают сервисы и репозитории. Интеграции возвращают нормализованные DTO, чтобы WB/Ozon различия не протекали в бизнес-логику.

## Схема БД

Основные таблицы:

- `users` — Telegram-пользователи, тариф, timezone, подписка;
- `marketplace_accounts` — кабинеты WB/Ozon, зашифрованные ключи, статус синхронизации;
- `products` — товары и внешние идентификаторы;
- `product_cost_history` — история себестоимости с периодами действия;
- `orders`, `order_items` — заказы и позиции;
- `profit_snapshots` — плановая и фактическая прибыль;
- `financial_report_rows` — нормализованные финансовые строки;
- `sales_events`, `returns_events` — продажи и возвраты;
- `stock_snapshots` — остатки и прогноз окончания;
- `notification_settings` — feature flags уведомлений;
- `alert_rules`, `alert_events` — правила и события алертов;
- `daily_reports` — отправленные отчёты;
- `sync_jobs`, `api_request_logs` — эксплуатационный журнал;
- `subscription_plans`, `subscriptions` — каркас монетизации.

Уникальные ограничения защищают от дублей заказов, финансовых строк, событий и алертов.

## Быстрый запуск

1. Создать `.env`:

```bash
cp .env.example .env
```

2. Сгенерировать ключ шифрования:

```bash
python -c "from app.core.security import generate_encryption_key; print(generate_encryption_key())"
```

3. Запустить инфраструктуру и сервисы:

```bash
docker compose up --build
```

4. Применить миграции:

```bash
docker compose run --rm api alembic upgrade head
```

Проверка API:

```bash
curl http://localhost:8000/health
```

## Локальная разработка без Docker

```bash
pip install -e ".[dev]"
alembic upgrade head
make api
make bot
make worker
```

## Тесты и качество

```bash
make test
make lint
make format
```

## Переменные окружения

Ключевые:

- `BOT_TOKEN` — токен Telegram Bot API;
- `DATABASE_URL` — async SQLAlchemy URL;
- `REDIS_URL` — Redis для arq;
- `ENCRYPTION_KEY` — Fernet key для шифрования API-ключей;
- `APP_SECRET_KEY` — секрет защищённых service endpoints;
- `ORDER_POLL_INTERVAL_SECONDS` — базовый интервал polling;
- `DEFAULT_TAX_RATE`, `DEFAULT_PACKAGE_COST` — значения по умолчанию.

## Этапы

### Этап 1. Каркас проекта

Готово:

- структура проекта;
- конфигурация;
- Docker Compose;
- PostgreSQL/Redis;
- модели;
- Alembic;
- запуск FastAPI, bot, worker;
- `/start` и главное меню.

Проверить:

- `docker compose up --build`;
- `alembic upgrade head`;
- `/health`;
- `pytest`.

### Этап 2. Пользователи и подключение API

Готово:

- регистрация Telegram-пользователя при `/start`;
- модель кабинетов;
- шифрование токенов;
- клиенты WB/Ozon.
- FSM-сценарии ввода ключей;
- проверка ключей через официальные read-only методы;
- список кабинетов;
- удаление кабинета пользователем.

TODO:

- расширить управление настройками уведомлений по каждому кабинету;
- добавить CLI/admin-команду для принудительного отключения проблемной интеграции;
- добавить проверку набора прав токена по конкретным разделам API, если маркетплейс начнёт отдавать scopes.

### Этап 3. Товары и себестоимость

Готово:

- таблицы товаров и истории себестоимости;
- сервис выбора себестоимости;
- Excel-шаблон и парсер.
- Telegram upload/download;
- применение импортированных строк к БД;
- ручной ввод себестоимости.
- синхронизация товаров WB/Ozon.

Формат ручного ввода себестоимости:

```text
Артикул; Себестоимость; Упаковка; Доп. расходы; Налог %; Дата начала
```

Пример:

```text
SKU-001; 520; 25; 0; 6; 2026-05-14
```

TODO:

- добавить экран товаров без себестоимости;
- добавить пагинацию списка товаров;
- расширить Ozon product sync детализацией карточек, если `/v3/product/list` вернул только минимальный набор;
- добавить импорт себестоимости с выбором поведения при дублях через интерфейс.

### Этапы 4-8

Готов MVP:

- polling заказов;
- сохранение с idempotency;
- карточка нового заказа;
- ежедневные отчёты;
- FBS-контроль;
- остатки;
- фактическая прибыль через `financial_report_rows`.

TODO:

- расширить список заказов пагинацией;
- отправлять созданные `AlertEvent` отдельной задачей доставки уведомлений;
- добавить точные адаптеры финансовых отчётов WB/Ozon по мере стабилизации форматов выгрузок;
- доработать прогноз окончания товара на основе продаж за 7 дней;
- добавить сравнение план/факт в Telegram-карточку заказа.

TODO:

- расширить worker schedule;
- добавить фактическое сопоставление финансовых строк;
- реализовать экранные разделы с пагинацией;
- добавить больше интеграционных тестов.

## Production checklist

- задать настоящий `ENCRYPTION_KEY`;
- хранить `.env` вне git;
- включить бэкапы PostgreSQL;
- настроить log rotation для `logs/*.log`;
- ограничить доступ к `/admin/errors`;
- настроить мониторинг worker-процессов;
- проверить лимиты WB/Ozon для каждого кабинета;
- добавить отдельного Telegram admin-бота или CLI для операций поддержки.
