# MP Control

Telegram-бот и web-кабинет для селлеров Wildberries и Ozon. Главная идея: вы получаете уведомление о новом заказе сразу с расчётом плановой прибыли или убытка по нему.

**Текущая версия:** 1.7.2

---

## Содержание

- [Основные возможности](#основные-возможности)
- [Архитектура](#архитектура)
- [Стек технологий](#стек-технологий)
- [Структура директорий](#структура-директорий)
- [Переменные окружения](#переменные-окружения)
- [Установка и запуск через Docker](#установка-и-запуск-через-docker)
- [Установка и запуск без Docker](#установка-и-запуск-без-docker)
- [Миграции Alembic](#миграции-alembic)
- [Основные команды для разработки](#основные-команды-для-разработки)
- [Telegram-бот](#telegram-бот)
- [Web-кабинет](#web-кабинет)
- [Синхронизация данных маркетплейсов](#синхронизация-данных-маркетплейсов)
- [Подписки и тарифы](#подписки-и-тарифы)
- [Финансовая аналитика](#финансовая-аналитика)
- [Уведомления](#уведомления)
- [Логи и диагностика](#логи-и-диагностика)
- [Частые проблемы и решения](#частые-проблемы-и-решения)
- [Production deployment](#production-deployment)
- [Версионирование](#версионирование)
- [Безопасность](#безопасность)
- [Roadmap](#roadmap)

---

## Основные возможности

- **Уведомления о заказах** — WB FBS/rFBS, Ozon FBS/FBO с расчётом плановой прибыли
- **Уведомления о выкупах и возвратах** — отслеживание завершённых продаж и возвратов
- **Синхронизация данных** — товары, заказы, продажи, остатки, финансовые отчёты WB и Ozon
- **Web-кабинет** — дашборд с KPI, аналитика, заказы, товары, план/факт, безубыточность, прогнозы
- **Контроль остатков** — алерты низкого остатка, прогноз out-of-stock, оценка упущенной выручки
- **Анализ прибыльности** — плановая и фактическая прибыль, план/факт отклонения, безубыточная цена
- **Управление себестоимостью** — ручной ввод, Excel-импорт, история изменений
- **Подписки и тарифы** — FREE, BASIC, PRO, ENTERPRISE с feature gating и оплатой через ЮKassa
- **Контроль ошибок** — классификация ошибок API, качество данных, мониторинг синхронизаций
- **Историческая загрузка** — backfill заказов, продаж и финансовых данных за выбранный период

---

## Архитектура

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Telegram    │     │   FastAPI    │     │     arq      │
│     Bot      │     │   (API+Web)  │     │   Worker     │
└──────┬───────┘     └──────┬───────┘     └──────┬───────┘
       │                    │                    │
       └────────────────────┼────────────────────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
       ┌──────▼──────┐ ┌───▼────┐ ┌──────▼──────┐
       │ PostgreSQL  │ │ Redis  │ │ WB / Ozon   │
       │   (async)   │ │        │ │   APIs      │
       └─────────────┘ └────────┘ └─────────────┘
```

**Правило слоёв:** Telegram-хендлеры не считают прибыль и не вызывают API маркетплейсов напрямую. Они обращаются к сервисам и репозиториям. Интеграционные клиенты возвращают нормализованные DTO, чтобы различия WB/Ozon не проникали в бизнес-логику.

**Идемпотентность:** Заказы, финансовые строки, события продаж и алерты используют уникальные ограничения. Повторные синхронизации обновляют существующие записи, а не создают дубли.

**Timezone-aware:** Все timestamps хранятся в UTC. Даты для пользователя конвертируются в его IANA timezone через helper `format_datetime_for_user`.

**Шифрование:** API-ключи и Ozon Client ID шифруются Fernet перед сохранением в `marketplace_accounts.encrypted_api_key`.

---

## Стек технологий

| Компонент | Технология |
|-----------|------------|
| Язык | Python 3.12 |
| Web-фреймворк | FastAPI + uvicorn |
| Telegram-бот | aiogram 3 |
| ORM | SQLAlchemy 2.0 |
| Миграции | Alembic |
| База данных | PostgreSQL 16 |
| Кэш / очереди | Redis 7 |
| Фоновые задачи | arq |
| Валидация | Pydantic 2 |
| Платежи | ЮKassa SDK |
| HTTP-клиент | httpx (async) |
| Форматирование | black, ruff |
| Типизация | mypy (strict) |
| Тесты | pytest, pytest-asyncio, pytest-httpx |

---

## Структура директорий

```
app/
  api/                 FastAPI health/admin endpoints, web routes
  bot/                 aiogram handlers, keyboards, states, FSM
  cli/                 CLI-команды (админские уведомления)
  core/                config, database, security (Fernet), logging
  integrations/        Wildberries и Ozon async API клиенты
  models/              SQLAlchemy 2.0 модели, enums, доменные сущности
  repositories/        Слой доступа к данным с idempotency helpers
  schemas/             Pydantic DTO для валидации и сериализации
  services/            Бизнес-логика (прибыль, алерты, уведомления, Excel)
  utils/               Общие утилиты (datetime с timezone)
  web/                 Web-кабинет (server-rendered HTML)
  workers/             arq фоновые задачи и cron-расписания
migrations/            Alembic миграции
tests/                 unit, integration, smoke тесты
deploy/                Скрипты production-развёртывания
docs/                  Документация (комиссии, тарифы)
```

---

## Переменные окружения

Ключевые переменные описаны в `.env.example`. Реальные значения должны храниться в файле `.env`, который **не должен** попадать в Git.

```env
# Приложение
APP_ENV=production
APP_DEBUG=false
APP_SECRET_KEY=your-secret-key

# Шифрование API-ключей (сгенерировать Fernet-ключ)
ENCRYPTION_KEY=PASTE_FERNET_KEY_HERE

# Telegram-бот
BOT_TOKEN=your_telegram_bot_token
ADMIN_TELEGRAM_IDS=123456789

# База данных
POSTGRES_DB=seller_profit_bot
POSTGRES_USER=seller_bot
POSTGRES_PASSWORD=your_secure_password
DATABASE_URL=postgresql+asyncpg://seller_bot:your_secure_password@postgres:5432/seller_profit_bot

# Redis
REDIS_URL=redis://redis:6379/0

# Базовые URL маркетплейсов (обычно не требуют изменения)
WB_BASE_MARKETPLACE_URL=https://marketplace-api.wildberries.ru
WB_BASE_COMMON_URL=https://common-api.wildberries.ru
WB_BASE_CONTENT_URL=https://content-api.wildberries.ru
WB_BASE_ANALYTICS_URL=https://seller-analytics-api.wildberries.ru
WB_BASE_FINANCE_URL=https://finance-api.wildberries.ru
WB_BASE_STATISTICS_URL=https://statistics-api.wildberries.ru
OZON_BASE_URL=https://api-seller.ozon.ru

# Web-кабинет (нужен публичный HTTPS-адрес — Telegram не принимает localhost)
WEB_BASE_URL=https://app.mpcontrol.online
WEB_APP_BASE_URL=https://app.mpcontrol.online
API_BASE_URL=https://api.mpcontrol.online
PUBLIC_SITE_URL=https://mpcontrol.online
WEB_LOGIN_TOKEN_TTL_MINUTES=10
WEB_SESSION_TTL_HOURS=168

# Настройки polling и backfill
ORDER_POLL_INTERVAL_SECONDS=180
BACKFILL_DEFAULT_DAYS=30
BACKFILL_CHUNK_DAYS=7

# Финансы по умолчанию
DEFAULT_TAX_RATE=0.06
DEFAULT_PACKAGE_COST=0

# ЮKassa
YOOKASSA_SHOP_ID=your_shop_id
YOOKASSA_SECRET_KEY=your_secret_key
YOOKASSA_RETURN_URL=https://app.mpcontrol.online/web/payment/success
YOOKASSA_WEBHOOK_URL=https://app.mpcontrol.online/webhooks/yookassa

# Поддержка
SUPPORT_TELEGRAM_USERNAME=mpcontrol_support

# Deployment
DEPLOY_PROJECT_DIR=/opt/mpcontrol
ENABLE_TELEGRAM_DEPLOY_COMMANDS=false
TELEGRAM_DEPLOY_MODE=trigger
```

> **Важно:** Никогда не коммитьте `.env` в репозиторий. Используйте `.env.example` как шаблон.

---

## Установка и запуск через Docker

### 1. Клонировать репозиторий

```bash
git clone https://github.com/kuzkabuh/MySellerRobot.git
cd MySellerRobot
```

### 2. Создать `.env`

```bash
cp .env.example .env
```

Заполните `.env` реальными значениями, особенно `BOT_TOKEN`, `DATABASE_URL`, `ENCRYPTION_KEY`.

### 3. Сгенерировать ключ шифрования

```bash
python -c "from app.core.security import generate_encryption_key; print(generate_encryption_key())"
```

Скопируйте результат в `ENCRYPTION_KEY` в `.env`.

### 4. Запустить сервисы

```bash
docker compose up -d --build
```

### 5. Применить миграции

```bash
docker compose exec api alembic upgrade head
```

### 6. Проверить работоспособность

```bash
docker compose ps
docker compose logs -f
docker compose logs -f api
docker compose logs -f bot
docker compose logs -f worker
curl http://localhost:8000/health
```

Сервисы Docker Compose:

| Сервис | Описание | Порт |
|--------|----------|------|
| `postgres` | PostgreSQL 16 | 5432 |
| `redis` | Redis 7 | 6379 |
| `api` | FastAPI (API + Web-кабинет) | 8000 |
| `bot` | Telegram-бот (aiogram) | — |
| `worker` | arq фоновые задачи | — |

---

## Установка и запуск без Docker

### Требования

- Python 3.12+
- PostgreSQL 14+
- Redis 6+

### 1. Установить зависимости

```bash
pip install -e ".[dev]"
```

### 2. Применить миграции

```bash
alembic upgrade head
```

### 3. Запустить сервисы (в отдельных терминалах)

```bash
make api      # FastAPI на порту 8000
make bot      # Telegram-бот
make worker   # arq фоновые задачи
```

---

## Миграции Alembic

```bash
# Текущая версия миграции
docker compose exec api alembic current

# Применить все миграции
docker compose exec api alembic upgrade head

# Создать новую миграцию
docker compose exec api alembic revision --autogenerate -m "описание изменений"

# Откатить на одну миграцию
docker compose exec api alembic downgrade -1

# Проверить наличие конфликтов (несколько heads)
docker compose exec api alembic heads
```

При конфликте нескольких heads:

```bash
docker compose exec api alembic merge -m "merge heads" <rev1> <rev2>
```

---

## Основные команды для разработки

```bash
# Тесты
make test
pytest
pytest tests/unit/test_profit_calculator.py
pytest --cov=app --cov-report=html

# Линтинг и форматирование
make lint       # ruff + mypy
make format     # black + ruff --fix

# Docker
make up         # docker compose up --build
make down       # docker compose down

# Миграции
make migrate    # alembic upgrade head
make revision m="описание"
```

---

## Telegram-бот

Ссылка на бота: **https://t.me/mpcontrolrobot**

### Назначение

- **Авторизация** — регистрация пользователя при `/start`, вход в web-кабинет через одноразовую ссылку
- **Уведомления** — заказы, выкупы, возвраты, алерты, ежедневные сводки
- **Аналитика** — сводки, прибыль, остатки, план/факт, безубыточность
- **Управление** — подключение кабинетов WB/Ozon, себестоимость, подписки, настройки

### Главное меню

```
📊 Сводка
🛒 Заказы
💰 Прибыль
📦 Товары и себестоимость
⚠ Контроль и уведомления
🌐 Web-кабинет
⚙ Настройки
🛠 Администрирование (только для ADMIN_TELEGRAM_IDS)
```

### Подключение кабинетов

1. `⚙ Настройки` → `Мои кабинеты` → `Подключить Wildberries` / `Подключить Ozon`
2. Следуйте инструкциям FSM-бота
3. После подключения автоматически запускается синхронизация товаров и историческая загрузка

### Вход в Web-кабинет

Нажмите `🌐 Web-кабинет` в Telegram — бот пришлёт одноразовую ссылку. После перехода создаётся HttpOnly session cookie, действительная 7 дней (`WEB_SESSION_TTL_HOURS`).

---

## Web-кабинет

Вход только через Telegram-ссылку. Базовый URL: `https://app.mpcontrol.online/web/`

### Основные разделы

| Раздел | URL | Описание |
|--------|-----|----------|
| Главная | `/web/` | KPI, динамика выручки и прибыли, фильтры периода/маркетплейса/модели продаж |
| Заказы | `/web/orders` | Таблица заказов и позиций с фильтрами |
| Детали заказа | `/web/orders/{id}` | Карточка заказа: информация, экономика, план/факт, исходный JSON |
| Прибыль | `/web/profit` | Прибыль по SKU: выручка, себестоимость, расходы МП, маржа, ROI |
| План/факт | `/web/plan-fact` | Сравнение плановых и фактических результатов, отклонения с причинами |
| Безубыточность | `/web/break-even` | Расчёт безубыточной цены, целевой маржи, симулятор изменения цены |
| Товары | `/web/products` | Единые карточки MasterProduct, связи WB/Ozon, аналитика |
| Карточка товара | `/web/products/{id}` | Детальная карточка: площадки, выручка, заказы, план/факт, остатки |
| Сопоставление | `/web/product-matching` | Ручное сопоставление товаров WB/Ozon |
| Остатки | `/web/stocks` | Текущие остатки, прогноз дней до out-of-stock, упущенная выручка |
| Продажи | `/web/sales` | События завершённых продаж (выкупы) |
| Возвраты | `/web/returns` | События возвратов |
| Алерты | `/web/alerts` | Последние события контроля |
| Качество данных | `/web/data-quality` | Оценка качества: себестоимость, комиссии, ошибки API, синхронизации |
| Аналитика | `/web/analytics` | Обзор бизнеса за 30 дней |
| Контроль ошибок | `/web/control` | Центр мониторинга ошибок синхронизации |
| Себестоимость | `/web/costs` | История себестоимости, редактирование |
| Профиль | `/web/profile` | Настройки пользователя, timezone, порог низкой маржи |
| Подписка | `/web/subscription` | Текущий тариф, лимиты, история платежей |
| Кабинеты | `/web/accounts` | Подключённые кабинеты WB/Ozon, статусы синхронизации |
| Настройки | `/web/settings` | Уведомления, порог низкой маржи |

> Некоторые разделы могут быть ограничены тарифом. Раздел «Контроль ошибок» и «Качество данных» находятся в развитии.

---

## Синхронизация данных маркетплейсов

### Wildberries API

| Источник | Методы | Данные |
|----------|--------|--------|
| FBS заказы | `GET /api/v3/orders/new`, `GET /api/v3/orders` | Сборочные задания, статусы |
| Карточки товаров | `POST /content/v2/get/cards/list` | Название, бренд, категория, изображение |
| Тарифы комиссий | `GET /api/v1/tariffs/commission` | Ставки комиссий по моделям |
| Остатки | `POST /api/analytics/v1/stocks-report/wb-warehouses` | Уровни остатков на складах WB |
| Продажи/выкупы | `GET /api/v1/supplier/sales` | Завершённые продажи |
| Финансовые отчёты | `POST /api/finance/v1/sales-reports/detailed` | Фактические удержания и начисления |
| Информация о продавце | `GET /api/v1/seller-info` | Данные продавца |
| Баланс | Finance-токен | Snapshot баланса |

> **Важно:** Старый WB finance API (`/api/v5/supplier/reportDetailByPeriod`) объявлен к отключению 15.07.2026. Проект использует новые v1 finance endpoints.

### Ozon Seller API

| Источник | Методы | Данные |
|----------|--------|--------|
| FBS отправления | `POST /v3/posting/fbs/list`, `POST /v3/posting/fbs/get` | Заказы, статусы, financial_data |
| FBO отправления | `POST /v2/posting/fbo/list` | FBO заказы |
| Неотгруженные FBS | `POST /v3/posting/fbs/unfulfilled/list` | Контроль дедлайнов |
| Товары | `POST /v3/product/list`, `POST /v3/product/info/list` | Каталог, детализация карточек |
| Остатки | `POST /v4/product/info/stocks` | Общие остатки |
| Возвраты | `POST /v1/returns/list` | События возвратов |
| Продавец | `POST /v1/seller/info` | Информация о продавце |

> **Важно:** Старые Ozon finance методы (`/v3/finance/transaction/list`) объявлены к отключению 06.07.2026.

### Типы синхронизации

| Задача | Расписание | Описание |
|--------|------------|----------|
| `poll_new_orders` | Каждые 3 мин | Новые заказы WB/Ozon |
| `sync_sale_events` | Каждые 15 мин | Выкупы и завершённые продажи |
| `sync_products` | Ежедневно 01:20 | Каталог товаров |
| `check_low_stocks` | 3× в день (8:10, 14:10, 20:10) | Остатки, прогноз out-of-stock |
| `check_fbs_deadlines` | Каждые 15 мин | Риски дедлайнов FBS/rFBS |
| `process_history_backfills` | Каждые 10 мин | Историческая загрузка |
| `sync_wb_daily_sales_reports` | Ежедневно 02:00 | WB sales за D-1/D-2/D-3 |
| `sync_ozon_catalog_enrichment` | Ежедневно 03:20 | Ozon склады, цены, акции |
| `sync_wb_commissions` | Ежедневно 03:10 | Тарифы комиссий WB |
| `check_ozon_commission_source` | Ежедневно 03:30 | Мониторинг страницы комиссий Ozon |
| `sync_wb_logistics_tariffs` | Ежедневно 03:50 | Тарифы логистики WB |
| `sync_wb_daily_financial_details` | Ежедневно 05:00 | Детальные финансовые данные WB |
| `send_daily_reports` | Ежедневно в 09:00 | Ежедневные сводки |

### Ограничения точности расчётов

Финансовые показатели зависят от доступности данных API:

- **EXACT** — данные из финансового отчёта WB/Ozon
- **ESTIMATED** — комиссия из тарифа WB или financial_data Ozon
- **PRELIMINARY** — fallback-оценка (базовая логистика WB FBS)

Если точная комиссия или логистика ещё недоступны, расчёт продолжается с предупреждением. Пользователь видит пометку «будет уточнена после финансового отчёта».

---

## Подписки и тарифы

Доступ к функциям зависит от активной подписки.

| Тариф | Цена/мес | Кабинеты | Заказы/мес | Возможности |
|-------|----------|----------|------------|-------------|
| **FREE** | 0 ₽ | 1 | 100 | Web-кабинет (базовый) |
| **BASIC** | 490 ₽ | 2 | 1 000 | Web-кабинет, аналитика, алерты |
| **PRO** | 1 490 ₽ | 5 | ∞ | Всё из BASIC + план/факт, безубыточность, прогноз остатков, приоритетная поддержка |
| **ENTERPRISE** | по договорённости | 999 | ∞ | Всё из PRO + API access |

### Периоды подписки

- **Месячная** — 30 дней
- **Годовая** — 365 дней (со скидкой)

### Правила

- Продление до окончания периода добавляет дни к текущему `expires_at`
- Продление истёкшей подписки считается от текущей даты
- Upgrade (BASIC → PRO) заменяет старую подписку статусом `REPLACED`
- Trial можно получить только один раз
- Администратор может вручную назначить тариф через `🛠 Администрирование` → `💳 Управление тарифами`

### Оплата

Интеграция с ЮKassa:

1. Выбор тарифа и периода в Telegram
2. Создание платежа с idempotency key
3. Webhook `payment.succeeded` активирует подписку
4. Webhook `payment.canceled` отменяет платёж

Webhook URL: `https://app.mpcontrol.online/webhooks/yookassa`

---

## Финансовая аналитика

### Расчёт прибыли

```
Прибыль = Выручка - Комиссия МП - Логистика - Эквайринг - Хранение
          - Возвраты - Прочие расходы МП - Себестоимость
          - Упаковка - Доп. расходы продавца - Налог
```

- **Выручка** — валовая цена продажи (не `expected_payout`)
- **Себестоимость** — берётся из `product_cost_history` на дату заказа
- **Комиссия** — из финансового отчёта, тарифа WB или financial_data Ozon
- **Налог** — по умолчанию 6% (`DEFAULT_TAX_RATE`), настраивается пользователем

### План/факт анализ

Сервис `PlanFactService` сравнивает плановые `ProfitSnapshot` с фактическими финансовыми результатами. Отклонения классифицируются:

- Факт ещё не получен
- Расходы маркетплейса выше плана
- Выручка ниже плана
- Факт лучше плана
- План совпал с фактом

### Безубыточность

Раздел `/web/break-even` рассчитывает:

- Безубыточную цену
- Цену для целевой маржи
- Результат симуляции изменения цены

Формула учитывает себестоимость, комиссию МП, логистику и налог.

---

## Уведомления

### Типы уведомлений

| Тип | Описание |
|-----|----------|
| Новый заказ | WB FBS/rFBS, Ozon FBS/FBO — сразу при обнаружении |
| Выкуп | Завершённая продажа WB/Ozon |
| Возврат | Событие возврата |
| FBS-дедлайн | Риск нарушения срока отгрузки |
| Низкий остаток | Товар ниже порогового уровня |
| Прогноз out-of-stock | Товар может закончиться в ближайшие дни |
| Ошибка синхронизации | Проблемы с API маркетплейса |
| Ежедневная сводка | Итоги дня в настроенное время |
| FBO-дайджест | Пакетное уведомление FBO-заказов (каждые 30 мин) |

### Настройка уведомлений

Каждый пользователь может включить/отключить типы уведомлений через:

- Telegram: `⚠ Контроль и уведомления` → `Уведомления`
- Web: `/web/settings`

### Режимы уведомлений FBO

- **Сразу** — каждое отправление отдельно
- **Дайджест 30 мин** — пакетная отправка
- **Только ежедневная сводка** — в составе daily report

---

## Логи и диагностика

### Базовые команды

```bash
# Git
git status
git log --oneline -10

# Docker
docker compose ps
docker compose logs --tail=200 api
docker compose logs --tail=200 bot
docker compose logs --tail=200 worker

# Миграции
docker compose exec api alembic current
docker compose exec api alembic heads

# Здоровье API
curl http://localhost:8000/health
```

### Локальные smoke-проверки

```bash
python -c "import app; import app.utils"
python -c "from app.core.config import get_settings; print(get_settings().app_env)"
python -c "from app.api.main import create_app; print(create_app().title)"
python -c "from app.bot.main import create_dispatcher; print(len(create_dispatcher().sub_routers))"
python -c "from app.workers.settings import WorkerSettings; print(len(WorkerSettings.functions))"
```

### Логи

- Контейнеры: `docker compose logs -f api`, `docker compose logs -f bot`, `docker compose logs -f worker`
- Файлы: `logs/*.log` (при маунте volume)
- Deploy-логи: `logs/deploy/`

---

## Частые проблемы и решения

### Не приходят уведомления

1. Проверьте, что бот запущен: `docker compose ps`
2. Проверьте логи worker: `docker compose logs --tail=200 worker`
3. Ищите события `order_poll_started`, `notifications_sent`, `send_failed`
4. Убедитесь, что уведомления включены в настройках
5. Проверьте, что кабинет активен и синхронизирован

### Не обновляются заказы

1. Проверьте статус кабинета в `⚙ Настройки` → `Мои кабинеты`
2. Проверьте логи worker на ошибки авторизации: `docker compose logs --tail=200 worker`
3. Убедитесь, что API-ключ WB/Ozon действителен
4. Проверьте rate limits маркетплейса
5. Запустите ручную синхронизацию: `🔄 Загрузить историю`

### Web-кабинет отдаёт 500

1. Проверьте логи API: `docker compose logs --tail=200 api`
2. Убедитесь, что миграции применены: `docker compose exec api alembic current`
3. Проверьте, что `WEB_BASE_URL` — публичный HTTPS-адрес
4. Проверьте подключение к PostgreSQL и Redis

### Миграции не применились

1. Проверьте текущую версию: `docker compose exec api alembic current`
2. Проверьте конфликты: `docker compose exec api alembic heads`
3. При нескольких heads: `docker compose exec api alembic merge -m "merge" <rev1> <rev2>`
4. Примените: `docker compose exec api alembic upgrade head`

### Подписка не активируется после оплаты

1. Проверьте, что webhook настроен в ЮKassa: `payment.succeeded`
2. Проверьте логи API: `docker compose logs --tail=200 api`
3. Проверьте таблицу платежей: статус должен быть `SUCCEEDED`
4. Проверьте задачу reconciliation: `reconcile_pending_payments` (каждые 20 мин)
5. Убедитесь, что `YOOKASSA_SHOP_ID` и `YOOKASSA_SECRET_KEY` корректны

---

## Production deployment

### Требования

- Ubuntu 22.04/24.04
- Docker Compose
- Nginx + Certbot (SSL)
- Домены: `mpcontrol.online`, `app.mpcontrol.online`, `api.mpcontrol.online`

### Первичная установка

```bash
git clone https://github.com/kuzkabuh/MySellerRobot.git /tmp/mpcontrol-src
cd /tmp/mpcontrol-src
sudo REPO_URL="https://github.com/kuzkabuh/MySellerRobot.git" \
  BRANCH="main" \
  SSL_EMAIL="owner@mpcontrol.online" \
  bash deploy/install.sh
```

### Обновление

```bash
cd /opt/mpcontrol
sudo bash deploy/update.sh
```

### Ручной backup

```bash
bash deploy/backup.sh
```

### Production compose

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

### Production checklist

- [ ] Настоящий `ENCRYPTION_KEY` (не из примера)
- [ ] `.env` вне git, `chmod 600`
- [ ] Бэкапы PostgreSQL настроены
- [ ] Log rotation для `logs/*.log`
- [ ] Доступ к `/admin/*` ограничен
- [ ] Мониторинг worker-процессов
- [ ] Лимиты WB/Ozon для каждого кабинета проверены
- [ ] HTTPS-сертификаты действительны
- [ ] Webhook ЮKassa настроен и проверен

---

## Версионирование

Версия хранится в двух файлах:

- `VERSION` — текстовый файл с номером версии
- `pyproject.toml` — поле `version` в секции `[project]`

Оба файла должны содержать одинаковую версию. Текущая версия: **1.7.2**.

### Обновление версии

```bash
# Обновить VERSION
echo "1.7.3" > VERSION

# Обновить pyproject.toml (поле version в [project])
# Затем закоммитить изменения

git add VERSION pyproject.toml
git commit -m "chore: bump version to 1.7.3"
git tag -a v1.7.3 -m "Release v1.7.3"
git push
git push --tags
```

---

## Безопасность

- **`.env` не коммитить** — токены, пароли, ключи хранятся только локально
- **API-ключи шифруются** — Fernet-шифрование перед сохранением в БД
- **Web-сессии** — HttpOnly cookie, одноразовые токены входа с SHA-256 hash
- **HTTPS обязателен** — Telegram не принимает localhost в URL-кнопках
- **Webhook URL** — проверяйте корректность webhook ЮKassa и ограничение доступа
- **Админские функции** — доступны только пользователям из `ADMIN_TELEGRAM_IDS`
- **Регулярные бэкапы** — PostgreSQL через `deploy/backup.sh`
- **Production-секреты** — не публиковать, не логировать, не передавать в открытом виде

---

## Roadmap

### Выполнено

- [x] Этап 0 — Аудит и проектирование
- [x] Этап 1 — FBO + FBS + rFBS уведомления
- [x] Этап 2 — Первичная историческая синхронизация
- [x] Этап 3 — Web-кабинет: каркас и авторизация
- [x] Этап 4 — Главный дашборд
- [x] Этап 5 — Заказы, прибыль и детальные карточки
- [x] Этап 6 — MasterProduct и сравнение WB/Ozon
- [x] Этап 7 — План/факт и отклонения
- [x] Этап 8 — Безубыточная цена и симулятор
- [x] Этап 9 — Остатки, прогноз out-of-stock
- [x] Этап 10 — Расширенные алерты и качество данных

### В планах

- [ ] Этап 11 — Ролевой доступ
- [ ] Этап 12 — AI-аналитик
- [ ] Этап 13 — Экспорты и финансовый раздел
- [ ] Этап 14 — Финальная стабилизация

---

## Автор / бренд

**KUZ'KA.SELLER BOT / MP Control**

Репозиторий: https://github.com/kuzkabuh/MySellerRobot

Web: https://mpcontrol.online

Telegram-бот: https://t.me/mpcontrolrobot

Поддержка: @mpcontrol_support
