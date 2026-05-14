# version: 1.1.0
# description: Product architecture, setup, API notes, and MVP status.
# updated: 2026-05-15

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

## Технический рефакторинг после этапов 0-2 итерации 2

Проведена диагностика запуска и упаковки проекта с настройкой `setuptools`:

```toml
[tool.setuptools.packages.find]
where = ["."]
include = ["app*"]
namespaces = false
```

Что исправлено:

- добавлен пакетный маркер `app/utils/__init__.py`, чтобы все внутренние Python-пакеты
  корректно находились без namespace packages;
- добавлены фабрики `create_bot`, `create_storage`, `create_dispatcher` для безопасных smoke-тестов
  Telegram-бота без запуска polling;
- расчёт плановой прибыли вынесен в `OrderProfitService`, теперь онлайн-заказы и исторический
  backfill используют один публичный сервис;
- настройки исторической загрузки вынесены в ENV: `BACKFILL_DEFAULT_DAYS`,
  `BACKFILL_CHUNK_DAYS`;
- worker-задача исторической синхронизации приведена к единым абсолютным импортам и отправляет
  пользователю сообщение о неуспешном завершении задачи;
- добавлены smoke-тесты для обнаружения пакета `app`, FastAPI factory, aiogram Dispatcher,
  worker settings и backfill-настроек.

Текущая версия после Этапа 4.2: `1.4.8`. Версия хранится в `VERSION` и в
`pyproject.toml`.

## Почему arq

Для фоновых задач выбран `arq`, потому что проект асинхронный: aiogram, FastAPI, httpx и клиенты маркетплейсов работают через async I/O. `arq` использует Redis, проще Celery для async-кода, поддерживает retries/job timeout и хорошо подходит для polling-задач: новые заказы, остатки, FBS-дедлайны, ежедневные отчёты. Celery мощнее для сложных distributed workflow, но в этом MVP дал бы больше инфраструктурной тяжести и синхронных обёрток.

## Проверенные официальные API

Проверено 14.05.2026 по официальным страницам WB API и Ozon Help/Seller API.

### Wildberries

Базовые домены:

- `https://marketplace-api.wildberries.ru` — FBS-заказы и поставки;
- `https://content-api.wildberries.ru` — карточки товаров;
- `https://seller-analytics-api.wildberries.ru` — аналитика и остатки;
- `https://statistics-api.wildberries.ru` — исторические заказы и продажи/выкупы;
- `https://finance-api.wildberries.ru` — финансовые отчёты.

Использованные/заложенные методы:

- `GET /api/v3/orders/new` — новые FBS сборочные задания;
- `GET /api/v3/orders` — список сборочных заданий за период;
- `POST /api/v3/orders/status` — статусы сборочных заданий;
- `POST /api/marketplace/v3/orders/meta` — метаданные сборочных заданий;
- `GET /api/v1/supplier/orders` — заказы из статистики WB для FBO/исторической сводки;
- `GET /api/v1/supplier/sales` — продажи/выкупы WB для событий завершённой продажи;
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
- `BACKFILL_DEFAULT_DAYS` — период первичной исторической загрузки после подключения кабинета;
- `BACKFILL_CHUNK_DAYS` — размер чанка исторической загрузки в днях;
- `WEB_BASE_URL` — публичный адрес API/web-сервиса для одноразовых ссылок из Telegram;
- `WEB_APP_BASE_URL` — альтернативное имя публичного web-адреса; если задано, используется для
  ссылок из Telegram;
- `WEB_LOGIN_TOKEN_TTL_MINUTES` — срок жизни одноразовой ссылки web-входа;
- `WEB_SESSION_TTL_HOURS` — срок жизни web-сессии в cookie;
- `DEFAULT_TAX_RATE`, `DEFAULT_PACKAGE_COST` — значения по умолчанию.

## Диагностика и эксплуатационные команды

Локальные smoke-проверки:

```bash
python -c "import app; import app.utils"
python -c "from app.core.config import get_settings; print(get_settings().app_env)"
python -c "from app.api.main import create_app; print(create_app().title)"
python -c "from app.bot.main import create_dispatcher; print(len(create_dispatcher().sub_routers))"
python -c "from app.workers.settings import WorkerSettings; print(len(WorkerSettings.functions))"
```

Проверка миграций:

```bash
python -m alembic history
python -m alembic heads
python -m alembic upgrade head
```

Docker-проверка:

```bash
docker compose build
docker compose run --rm api alembic upgrade head
docker compose up -d
docker compose ps
docker compose logs api --tail=100
docker compose logs bot --tail=100
docker compose logs worker --tail=100
curl http://localhost:8000/health
```

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

## Итерация 2. Этап 1: FBO + FBS + rFBS

Готово:

- модель заказа расширена полями `fulfillment_type`, `urgency_type`, `source_event_type`,
  `processing_deadline_at`, `requires_seller_action`, `warehouse_type`, `delivery_schema`,
  `raw_status`, `normalized_status`, `first_notified_at`, `last_notified_at`;
- добавлены настройки уведомлений для FBS, rFBS, FBO и режим FBO: сразу, дайджест 30 минут,
  только ежедневная сводка;
- Ozon polling получает FBS/rFBS через `POST /v3/posting/fbs/list` и FBO через
  `POST /v2/posting/fbo/list`;
- добавлена поддержка Ozon `POST /v3/posting/fbs/unfulfilled/list` для следующих этапов
  FBS/rFBS-контроля;
- WB FBS использует официальный `GET /api/v3/orders/new`; FBO-события нормализуются из
  отчётных/статистических данных как информационные события, без имитации онлайн-FBO;
- Telegram-карточки различают срочные FBS/rFBS-заказы и справочные FBO-заказы;
- добавлена идемпотентная очередь `fbo_digest_queue` и worker-задача `send_fbo_digests`;
- FBS/rFBS deadline-контроль теперь опирается на `processing_deadline_at` и
  `requires_seller_action`;
- добавлены unit/integration tests для нормализации, политики уведомлений, FBO-дайджеста и
  API-клиентов.

Проверенные официальные источники API:

- Wildberries FBS Orders: `https://dev.wildberries.ru/en/docs/openapi/orders-fbs`;
- Ozon Seller API: `https://docs.ozon.ru/global/api/intro/`;
- Ozon FBS methods из официальной справки включают `POST /v3/posting/fbs/list`,
  `POST /v3/posting/fbs/get`, `POST /v3/posting/fbs/unfulfilled/list`.

Команды проверки:

```bash
docker compose run --rm api alembic upgrade head
docker compose run --rm api pytest
docker compose run --rm api ruff check app tests migrations
docker compose run --rm api mypy app
```

Локально без Docker:

```bash
python -m alembic upgrade head
python -m pytest
python -m ruff check app tests migrations
python -m mypy app
```

## Итерация 2. Этап 2: первичная историческая синхронизация

Готово:

- после подключения кабинета бот проверяет ключ, синхронизирует товары и создаёт задачу
  `INITIAL_HISTORY_BACKFILL` за последние 30 дней;
- в карточке кабинета добавлена кнопка `🔄 Загрузить историю` с периодами 30 / 90 / 180 дней;
- `sync_jobs` расширена полями периода, прогресса, статуса, счётчиков и JSON-метаданных;
- добавлен сервис `HistoryBackfillService` с чанками по 7 дней, идемпотентным импортом и
  статусами `COMPLETED`, `COMPLETED_WITH_WARNINGS`, `FAILED`, `CANCELLED`;
- добавлен worker `process_history_backfills`, который берёт pending-задачи и присылает
  Telegram-уведомление о завершении;
- исторические заказы сохраняются через upsert: повторный импорт не создаёт дубли, а уточняет
  уже сохранённые записи;
- для импортированных заказов запускается расчёт плановой прибыли с учётом истории
  себестоимости;
- продажи, возвраты и финансовые строки сохраняются отдельно в `sales_events`,
  `returns_events`, `financial_report_rows`.

Что грузится:

- Wildberries:
  - FBS-заказы за период через `GET /api/v3/orders`;
  - финансовые строки и отчётные FBO/реализации через новую ветку
    `POST /api/finance/v1/sales-reports/detailed`;
  - старый `GET /api/v5/supplier/reportDetailByPeriod` не используется, так как официально
    объявлен к отключению 15 июля 2026 года.
- Ozon:
  - FBS/rFBS через `POST /v3/posting/fbs/list`;
  - FBO через `POST /v2/posting/fbo/list`;
  - возвраты через `POST /v1/returns/list`;
  - финансовые отчёты помечаются как отдельный частичный блок, потому что часть отчётов
    формируется асинхронно и может быть недоступна сразу.

Как запустить вручную из Telegram:

1. `⚙ Настройки`;
2. `Мои кабинеты`;
3. выбрать кабинет;
4. `🔄 Загрузить историю`;
5. выбрать период.

Как проверить через worker:

```bash
docker compose run --rm api alembic upgrade head
docker compose up -d worker
docker compose run --rm api pytest
```

Локальные команды:

```bash
python -m alembic upgrade head
python -m pytest
python -m ruff check app tests migrations
python -m mypy app
```

Новый порядок этапов:

- Этап 0 — аудит и проектирование — выполнен.
- Этап 1 — FBO + FBS + rFBS уведомления — выполнен.
- Этап 2 — первичная историческая синхронизация данных — выполнен.
- Этап 3 — Web-кабинет: каркас и авторизация.
- Этап 4 — Главный дашборд.
- Этап 5 — Заказы, прибыль и детальные карточки.
- Этап 6 — MasterProduct и сравнение WB/Ozon.
- Этап 7 — План/факт и отклонения.
- Этап 8 — Безубыточная цена и симулятор.
- Этап 9 — Остатки, прогноз out-of-stock и потери выручки.
- Этап 10 — Расширенные алерты и качество данных.
- Этап 11 — Ролевой доступ.
- Этап 12 — AI-аналитик.
- Этап 13 — Экспорты и финансовый раздел.
- Этап 14 — Финальная стабилизация.

## Итерация 2. Этап 3: web-кабинет, каркас и авторизация

Готово:

- выбран быстрый MVP-подход: FastAPI routes + серверный HTML без отдельной сборки frontend;
- добавлены таблицы `one_time_login_tokens` и `user_web_sessions`;
- вход в web-кабинет выполняется через одноразовую ссылку из Telegram;
- в БД хранится только SHA-256 hash одноразового токена и web-сессии;
- одноразовая ссылка помечается использованной после входа;
- web-сессия хранится в `HttpOnly` cookie;
- добавлен базовый layout web-кабинета с левым меню:
  Главная, Заказы, Прибыль, Товары, Остатки, Аналитика, Контроль, Себестоимость, Настройки;
- добавлена базовая главная страница `/web/` с KPI за сегодня;
- в Telegram-главное меню добавлена кнопка `🌐 Web-кабинет`;
- добавлены smoke/unit tests для маршрутов web-кабинета и сервиса авторизации.

Как проверить:

```bash
docker compose run --rm api alembic upgrade head
docker compose up -d
curl http://localhost:8000/health
```

Проверка входа:

1. Открыть бота в Telegram.
2. Нажать `🌐 Web-кабинет`.
3. Перейти по одноразовой ссылке.
4. После входа откроется `/web/`.

Локальные проверки:

```bash
python -m alembic upgrade head
python -m pytest
python -m ruff check app tests migrations
python -m mypy app
```

## Итерация 2. Этап 3.1: стабилизация Telegram-бота и UX

Готово:

- добавлена кликабельная кнопка `🔗 Открыть web-кабинет` через `InlineKeyboardButton(url=...)`;
- главное меню Telegram приведено к актуальной структуре:
  `📊 Сводка`, `🛒 Заказы`, `💰 Прибыль`, `📦 Товары и себестоимость`,
  `⚠ Контроль и уведомления`, `🌐 Web-кабинет`, `⚙ Настройки`;
- для администраторов из `ADMIN_TELEGRAM_IDS` появляется пункт `🛠 Администрирование`;
- добавлены подменю сводки, заказов, прибыли, контроля и уведомлений;
- исправлена сводка: активные WB/Ozon кабинеты показываются отдельными блоками даже при нулевых
  значениях за период;
- сводка использует timezone пользователя при выборе границ дня;
- в сводке дополнительно учитываются `sales_events` и `returns_events`;
- исправлена причина падения уведомлений о заказах: PostgreSQL enum `notificationtype` расширен
  значениями `ORDER_FBS`, `ORDER_RFBS`, `ORDER_FBO`, `FBO_DIGEST`;
- worker polling теперь пишет диагностические логи: сколько кабинетов опрошено, сколько заказов
  получено, создано, подготовлено и отправлено уведомлений;
- ошибки Telegram-отправки логируются отдельно и не ломают обработку остальных заказов;
- добавлено базовое админское меню:
  пользователи, кабинеты, синхронизации, системная статистика, диагностика заказов;
- добавлены тесты меню, web-кнопки, summary WB/Ozon/нули и enum-регрессии.

Как проверить уведомления и polling:

```bash
docker compose run --rm api alembic upgrade head
docker compose up -d worker bot
docker compose logs worker --tail=200
```

В логах worker должны быть события:

```text
order_poll_started
order_poll_account_finished
order_poll_notifications_sent
```

Если маркетплейс вернул новый заказ, `notifications_sent` должен быть больше нуля, а заказ
получит `first_notified_at`.

Как проверить Telegram UX:

1. `/start` — открывает новое главное меню.
2. `📊 Сводка` → `Сегодня` — показывает Wildberries и Ozon отдельными блоками.
3. `🌐 Web-кабинет` — присылает кнопку `🔗 Открыть web-кабинет`.
4. `⚠ Контроль и уведомления` → `Уведомления о заказах` — позволяет включить/отключить
   оперативные уведомления.
5. Для админа из `ADMIN_TELEGRAM_IDS` в главном меню доступно `🛠 Администрирование`.

## Итерация 2. Этап 3.2: Telegram ↔ Web, WB-сводка и выкупы

Готово:

- исправлен сценарий `🌐 Web-кабинет`: бот обрабатывает и callback-кнопку, и текст главного меню;
- если `WEB_BASE_URL` указывает на `localhost` или непубличный URL, бот не отправляет некликабельную
  Telegram-кнопку, а показывает понятное сообщение для настройки публичного HTTPS-адреса;
- WB-сводка теперь использует не только FBS-сборочные задания, но и официальный Statistics API:
  `GET /api/v1/supplier/orders` для заказов и `GET /api/v1/supplier/sales` для продаж/выкупов;
- исторический backfill WB также загружает статистические заказы и продажи, чтобы новый кабинет не
  показывал пустой дашборд при наличии заказов в кабинете WB;
- добавлена отдельная нормализованная сущность завершённой продажи в `sales_events`:
  `BUYOUT`, `SALE_COMPLETED`, `DELIVERED_TO_CUSTOMER`;
- добавлены уведомления о выкупах WB и завершённых продажах Ozon, отдельно от уведомлений о новых
  заказах;
- в `⚠ Контроль и уведомления` добавлены настройки уведомлений о выкупах;
- сводка разделяет заказы и выкупы/завершённые продажи:
  `Плановая прибыль по заказам` и `Плановая прибыль по выкупам`;
- админское меню дополнено диагностикой Wildberries и диагностикой событий.

Термины в проекте:

- заказ — покупатель оформил заказ, событие хранится в `orders`;
- выкуп / завершённая продажа — покупатель фактически забрал товар или маркетплейс зафиксировал
  завершение продажи, событие хранится в `sales_events`;
- возврат — отдельное событие в `returns_events`;
- финансовое отражение — фактические начисления и удержания в `financial_report_rows`, они не
  смешиваются с заказами и выкупами.

Как проверить переход в web:

```bash
docker compose up -d bot api
```

1. В `.env` указать публичный HTTPS-адрес:
   `WEB_BASE_URL=https://seller.example.com`.
2. В Telegram нажать `🌐 Web-кабинет`.
3. Бот должен прислать сообщение с URL-кнопкой `🔗 Открыть web-кабинет`.

Важно: Telegram не принимает `localhost` в `InlineKeyboardButton(url=...)`. Для локальной разработки
используйте публичный tunnel или внешний HTTPS-домен.

Как проверить WB-заказы в сводке:

```bash
docker compose run --rm api alembic upgrade head
docker compose up -d worker bot
docker compose logs worker --tail=200
```

В логах worker должны появляться события `sale_events_sync_finished` и `order_poll_account_finished`.
Для администратора доступно:

1. `🛠 Администрирование`;
2. `Диагностика Wildberries`;
3. `Диагностика событий`.

Эти разделы показывают последнюю WB-синхронизацию, количество заказов за сегодня/вчера, последний
WB-заказ, последние выкупы и количество отправленных уведомлений.

Как проверить уведомления о выкупах:

```bash
docker compose logs worker --tail=200
```

При получении новых записей из `GET /api/v1/supplier/sales` или завершённых Ozon posting бот
отправляет сообщение:

```text
✅ Выкуп товара — Wildberries
```

или:

```text
✅ Продажа завершена — Ozon
```

Повторная синхронизация не должна создавать дубли: уникальность обеспечивается по
`marketplace_account_id`, `marketplace`, `external_event_id`.

## Итерация 2. Этап 4: главный web-дашборд

Готово:

- главная страница `/web/` стала рабочим дашбордом вместо базовой заглушки;
- добавлены фильтры:
  период `Сегодня`, `Вчера`, `7 дней`, `30 дней`, произвольный период;
- добавлены фильтры по маркетплейсу: все, Wildberries, Ozon;
- добавлены фильтры по модели продаж: все, FBO, FBS, rFBS;
- KPI-карточки показывают:
  выручку, заказы, продажи, плановую прибыль, фактическую прибыль, возвраты,
  среднюю маржу и убыточные заказы;
- для ключевых KPI выводится сравнение с предыдущим аналогичным периодом;
- добавлены графики:
  выручка по дням, плановая прибыль по дням, заказы vs продажи,
  возвраты, FBO/FBS/rFBS, Wildberries vs Ozon;
- графики строятся серверно через inline SVG, поэтому dashboard не зависит от внешних CDN;
- фильтры и группировка дат используют timezone пользователя;
- добавлены unit-тесты фильтров, сравнения периодов и базового HTML-рендера dashboard.

Как проверить web-дашборд:

```bash
docker compose run --rm api alembic upgrade head
docker compose up -d api bot worker
curl http://localhost:8000/health
```

После этого:

1. В Telegram нажать `🌐 Web-кабинет`.
2. Перейти по одноразовой ссылке.
3. Открыть `/web/`.
4. Проверить фильтры периода, маркетплейса и модели продаж.

Для локальной проверки без Telegram можно создать одноразовую ссылку через сервис
`WebAuthService` в shell/API-контейнере, если в БД уже есть пользователь.

## Итерация 2. Этап 4.1: production-развёртывание

Готово:

- добавлен отдельный production compose: `docker-compose.prod.yml`;
- добавлены скрипты:
  `deploy/install.sh`, `deploy/update.sh`, `deploy/backup.sh`;
- добавлен Nginx template для доменов:
  `mpcontrol.online`, `www.mpcontrol.online`, `app.mpcontrol.online`,
  `api.mpcontrol.online`, `bot.mpcontrol.online`;
- установка ориентирована на Ubuntu 22.04/24.04, Docker Compose, host Nginx и Certbot;
- `.env` не перезаписывается ни при установке, ни при обновлении;
- перед обновлением выполняется backup PostgreSQL в `/opt/mpcontrol/backups`;
- миграции Alembic применяются автоматически при install/update;
- добавлена подробная инструкция: `deploy/README_DEPLOY.md`.

Первичная установка на сервере:

```bash
git clone https://github.com/kuzkabuh/MySellerRobot.git /tmp/mpcontrol-src
cd /tmp/mpcontrol-src
sudo REPO_URL="https://github.com/kuzkabuh/MySellerRobot.git" \
  BRANCH="main" \
  SSL_EMAIL="owner@mpcontrol.online" \
  bash deploy/install.sh
```

Обновление:

```bash
cd /opt/mpcontrol
sudo bash deploy/update.sh
```

Подробности DNS, GitHub Deploy Key, `.env`, SSL, логов и troubleshooting находятся в
`deploy/README_DEPLOY.md`.

## Итерация 2. Этап 4.2: CI/CD, backup и обновления из Telegram

Готово:

- добавлен CI workflow `.github/workflows/ci.yml`: ruff, black, mypy, pytest,
  Alembic upgrade на тестовой PostgreSQL и Docker build;
- добавлен production deploy workflow `.github/workflows/deploy-production.yml`;
- `deploy/update.sh` поддерживает обычный режим, `--non-interactive` и `--check-only`;
- перед обновлением создаётся backup PostgreSQL, `.env` и metadata JSON;
- обновления защищены lock-файлом в `runtime/update.lock`;
- результат последнего deploy сохраняется в `runtime/last_update_status.json`;
- администраторы получают Telegram-уведомление об успехе или ошибке обновления;
- в Telegram-админке появился раздел `🚀 Обновление и деплой`.

GitHub Secrets для production deploy:

```text
PROD_SSH_HOST
PROD_SSH_PORT
PROD_SSH_USER
PROD_SSH_PRIVATE_KEY
PROD_PROJECT_DIR
PROD_BRANCH
```

Ручная проверка обновлений на сервере:

```bash
cd /opt/mpcontrol
bash deploy/update.sh --check-only
```

Безопасный ручной deploy:

```bash
cd /opt/mpcontrol
bash deploy/update.sh --non-interactive
```

Telegram-админка:

1. Открыть `🛠 Администрирование`.
2. Перейти в `🚀 Обновление и деплой`.
3. Проверить текущую версию, наличие обновлений, статус последнего deploy, лог и backup.
4. Для запуска обновления из Telegram включить на сервере
   `ENABLE_TELEGRAM_DEPLOY_COMMANDS=true`. По умолчанию запуск shell-команды из Telegram
   отключён, но просмотр статусов и логов работает.

## Production checklist

- задать настоящий `ENCRYPTION_KEY`;
- хранить `.env` вне git;
- включить бэкапы PostgreSQL;
- настроить log rotation для `logs/*.log`;
- ограничить доступ к `/admin/errors`;
- настроить мониторинг worker-процессов;
- проверить лимиты WB/Ozon для каждого кабинета;
- добавить отдельного Telegram admin-бота или CLI для операций поддержки.
