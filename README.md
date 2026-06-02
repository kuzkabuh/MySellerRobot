# MP Control

MP Control — SaaS-сервис для селлеров Wildberries и Ozon. Проект объединяет
Telegram-бота, web-кабинет, аналитику, уведомления, подписки, тарифы, промокоды,
платежи YooKassa, синхронизации маркетплейсов, контроль МРЦ и инструменты управления
ценами WB.

## Версия

Текущая версия: **1.9.1**

## Возможности

### Telegram-бот

- регистрация пользователя через `/start`;
- подключение кабинетов Wildberries и Ozon;
- уведомления о заказах, продажах, возвратах, ошибках и низкой марже;
- просмотр заказов, прибыли, остатков, аналитики и подключённых кабинетов;
- запуск синхронизаций из меню бота;

### Резервные копии

- ежедневный backup PostgreSQL БД через `scripts/backup_daily.sh`;
- архив важных файлов проекта в `/opt/mpcontrol/backups/daily`;
- Telegram-уведомления администраторам о статусе backup;
- systemd timer: `deploy/systemd/mpcontrol-backup.timer`;
- инструкция восстановления: `docs/BACKUP_RESTORE.md`.

Включение на сервере:

```bash
sudo cp deploy/systemd/mpcontrol-backup.service /etc/systemd/system/mpcontrol-backup.service
sudo cp deploy/systemd/mpcontrol-backup.timer /etc/systemd/system/mpcontrol-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now mpcontrol-backup.timer
systemctl list-timers | grep mpcontrol
```
- настройка уведомлений, часового пояса и порога низкой маржи;
- просмотр подписки, тарифов и истории платежей;
- покупка и продление подписки через YooKassa;
- административная панель для тарифов, промокодов, диагностики и деплоя.

### Web-кабинет

- dashboard с KPI и быстрыми переходами;
- заказы, продажи, возвраты и детализация заказа;
- прибыль, план/факт, безубыточность и unit-экономика;
- товары, сопоставление WB/Ozon, себестоимость и Excel-импорт;
- остатки, алерты, качество данных и контроль ошибок;
- цены и акции WB, МРЦ, автоакции, рекомендации и применение цен;
- подключённые кабинеты маркетплейсов и ручной запуск синхронизаций;
- профиль, настройки, подписка и история платежей;
- web-админка тарифов, промокодов, пользователей, платежей, уведомлений,
  audit log, sync status, комиссий и логистики WB.

### Админский интерфейс

- Telegram-админка: пользователи, кабинеты, тарифы, промокоды, синхронизации,
  системная статистика, диагностика заказов/WB/событий, деплой и бэкапы;
- web-админка: тарифы, промокоды, комиссии маркетплейсов и тарифы логистики WB;
- доступ к админским функциям ограничивается `ADMIN_TELEGRAM_IDS`.

### Подписки и тарифы

- тарифы хранятся в БД и управляются через web-админку и Telegram-админку;
- поддерживаются тарифные коды FREE, BASIC, PRO и ENTERPRISE;
- цены, лимиты и публичность тарифов редактируются администратором;
- ограничения доступа проверяются единым `FeatureAccessService.can_use(user_id, feature_code)`;
- администратор может назначать тариф пользователю вручную.

### Промокоды

- процентная скидка;
- фиксированная скидка;
- бесплатные дни;
- лимиты использования;
- срок действия;
- применимость к тарифам и периодам;
- режим только для новых пользователей;
- история использований и статистика.

### Платежи YooKassa

- создание платежей на покупку или продление подписки;
- return pages `/payment/success` и `/payment/cancel`;
- webhook `/webhooks/yookassa` для `payment.succeeded` и `payment.canceled`;
- идемпотентная обработка webhook по provider payment id;
- активация подписки после успешной оплаты;
- поддержка промокодов при оплате.

### Интеграции маркетплейсов

- Wildberries: заказы, продажи, выкупы, возвраты, товары, остатки, цены, акции,
  комиссии, логистика, финансовые отчёты и баланс;
- Ozon: FBS/FBO отправления, товары, остатки, каталог, комиссии, возвраты и баланс;
- API-ключи и Ozon Client ID хранятся в зашифрованном виде.

### Автоматизация

- фоновый polling новых заказов;
- синхронизация продаж, выкупов, остатков, товаров и отчётов;
- FBO digest, контроль FBS/rFBS сроков и low-stock alerts;
- ежедневные отчёты;
- backfill исторических данных;
- классификация ошибок интеграций и аудит важных действий.

## Архитектура проекта

```text
app/
  api/                 FastAPI-приложение, health/admin endpoints, webhooks
  bot/                 aiogram-бот, handlers, keyboards, states, formatters
  cli/                 CLI-команды для обслуживания и админских операций
  core/                конфигурация, БД, Redis, безопасность, logging
  integrations/        async-клиенты Wildberries, Ozon и YooKassa
  models/              SQLAlchemy-модели и enums
  repositories/        слой доступа к данным и idempotency helpers
  schemas/             Pydantic DTO
  services/            бизнес-логика: прибыль, подписки, цены, синхронизации
  utils/               общие утилиты
  web/                 server-rendered web-кабинет и админские роуты
  workers/             arq задачи и cron-расписания
deploy/                install/update/backup scripts, nginx и systemd templates
docs/                  дополнительная документация
migrations/            Alembic-миграции
scripts/               вспомогательные проверки
tests/                 unit и integration tests
logs/                  локальные логи приложения
runtime/               runtime-файлы и trigger-файлы деплоя
backups/               локальные/серверные бэкапы
```

Основные процессы:

- `api` — FastAPI, web-кабинет и webhooks;
- `bot` — Telegram-бот на aiogram 3;
- `worker` — фоновые задачи arq;
- `postgres` — PostgreSQL;
- `redis` — Redis для очередей и storage.

## Технологический стек

- Python 3.12;
- FastAPI и uvicorn;
- aiogram 3;
- SQLAlchemy 2 и Alembic;
- PostgreSQL 16;
- Redis 7 и arq;
- Pydantic 2;
- httpx;
- openpyxl;
- Playwright для опционального браузерного fallback импорта комиссий Ozon;
- YooKassa SDK;
- Docker и Docker Compose;
- pytest, ruff, black и mypy.

## Переменные окружения

Шаблон находится в `.env.example`. Реальные значения храните только в `.env`, который
не должен попадать в Git. В публичной документации используйте только example-значения.

```env
APP_ENV=production
APP_DEBUG=false
APP_SECRET_KEY=change_me
ENCRYPTION_KEY=PASTE_FERNET_KEY_HERE

BOT_TOKEN=0000000000:example
ADMIN_TELEGRAM_IDS=123456789

POSTGRES_DB=mpcontrol_db
POSTGRES_USER=mpcontrol_user
POSTGRES_PASSWORD=change_me
DATABASE_URL=postgresql+asyncpg://mpcontrol_user:change_me@postgres:5432/mpcontrol_db
REDIS_URL=redis://redis:6379/0

WEB_BASE_URL=https://example.com
WEB_APP_BASE_URL=https://example.com
API_BASE_URL=https://api.example.com
PUBLIC_SITE_URL=https://example.com
BOT_WEBHOOK_BASE_URL=https://bot.mpcontrol.online
BOT_WEBHOOK_PATH=/webhook/telegram
BOT_WEBHOOK_SECRET=
BOT_WEBHOOK_ENABLED=false
WEB_LOGIN_TOKEN_TTL_MINUTES=10
WEB_SESSION_TTL_HOURS=168

YOOKASSA_SHOP_ID=example_shop_id
YOOKASSA_SECRET_KEY=example_secret_key
YOOKASSA_RETURN_URL=https://example.com/payment/success
YOOKASSA_WEBHOOK_URL=https://example.com/webhooks/yookassa

ORDER_POLL_INTERVAL_SECONDS=180
BACKFILL_DEFAULT_DAYS=30
BACKFILL_CHUNK_DAYS=7
DAILY_REPORT_HOUR=9
DEFAULT_TAX_RATE=0.06
DEFAULT_PACKAGE_COST=0
LOG_LEVEL=INFO

WB_BASE_MARKETPLACE_URL=https://marketplace-api.wildberries.ru
WB_BASE_COMMON_URL=https://common-api.wildberries.ru
WB_BASE_CONTENT_URL=https://content-api.wildberries.ru
WB_BASE_ANALYTICS_URL=https://seller-analytics-api.wildberries.ru
WB_BASE_FINANCE_URL=https://finance-api.wildberries.ru
WB_BASE_STATISTICS_URL=https://statistics-api.wildberries.ru
WB_BASE_CALENDAR_URL=https://dp-calendar-api.wildberries.ru
WB_BASE_DISCOUNTS_PRICES_URL=https://discounts-prices-api.wildberries.ru
OZON_BASE_URL=https://api-seller.ozon.ru

SUPPORT_TELEGRAM_USERNAME=mpcontrol_support
DEPLOY_PROJECT_DIR=/opt/example-app
DEPLOY_LOG_DIR=/opt/example-app/logs/deploy
DEPLOY_RUNTIME_DIR=/opt/example-app/runtime
BACKUP_DIR=/opt/example-app/backups
```

### Production domain configuration for mpcontrol.online

На production-сервере `.env` не должен содержать `example.com` или
`/opt/example-app`. Для текущего контура MP Control используйте реальные значения:

```env
WEB_BASE_URL=https://app.mpcontrol.online
WEB_APP_BASE_URL=https://app.mpcontrol.online
API_BASE_URL=https://app.mpcontrol.online
PUBLIC_SITE_URL=https://mpcontrol.online
BOT_WEBHOOK_BASE_URL=https://bot.mpcontrol.online
BOT_WEBHOOK_PATH=/webhook/telegram
BOT_WEBHOOK_SECRET=
BOT_WEBHOOK_ENABLED=false
YOOKASSA_RETURN_URL=https://app.mpcontrol.online/payment/success
YOOKASSA_WEBHOOK_URL=https://app.mpcontrol.online/webhooks/yookassa
DEPLOY_PROJECT_DIR=/opt/mpcontrol
DEPLOY_LOG_DIR=/opt/mpcontrol/logs/deploy
DEPLOY_RUNTIME_DIR=/opt/mpcontrol/runtime
BACKUP_DIR=/opt/mpcontrol/backups
```

`deploy/update.sh` строит публичный healthcheck URL из `API_BASE_URL`, затем из
`WEB_APP_BASE_URL`, затем из `WEB_BASE_URL`, затем из `PUBLIC_SITE_URL`. Если в
`APP_ENV=production` найдены placeholder-домены или placeholder-пути, деплой
останавливается до сборки Docker-образов.

Telegram webhook использует отдельный домен и не должен устанавливаться на
`https://app.mpcontrol.online`:

```text
https://bot.mpcontrol.online/webhook/telegram
```

FastAPI route webhook находится в `app/api/telegram_webhook.py`: `POST /webhook/telegram`.
Домен `bot.mpcontrol.online` должен проксировать только технические endpoints бота,
например `/webhook/telegram` и `/health`; web-кабинет `/web/` на этом домене открывать
нельзя.

Никогда не публикуйте реальные Telegram token, пароли БД, WB/Ozon API-ключи,
YooKassa secret key, cookie-файлы, OAuth-токены и банковские данные.

## Установка и запуск

### Локальный запуск через Docker

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec api alembic upgrade head
docker compose ps
docker compose logs -f api bot worker --tail=200
```

FastAPI будет доступен на `http://localhost:8000`, web-кабинет — на
`http://localhost:8000/web/`.

### Локальный запуск без Docker

```bash
pip install -e ".[dev]"
alembic upgrade head
make api
make bot
make worker
```

Для запуска без Docker нужны доступные PostgreSQL и Redis, а `DATABASE_URL` и
`REDIS_URL` должны указывать на эти сервисы.

### Production запуск

```bash
cp .env.example .env
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
docker compose -f docker-compose.prod.yml ps
```

В production сервис `api` слушает `127.0.0.1:8000:8000`; внешний HTTPS обычно
настраивается через nginx из шаблона `deploy/nginx/mpcontrol.conf.template`.
Production-образ ставит только runtime-зависимости. Playwright/Chromium для
браузерного fallback импорта комиссий Ozon не входит в образ по умолчанию; если этот
режим действительно нужен, собирайте с build arg `INSTALL_BROWSER=true` и включайте
`OZON_COMMISSIONS_BROWSER_FALLBACK_ENABLED=1`.

## Миграции БД

Миграции создаются и применяются через Alembic. Старые миграции не редактируйте без
крайней необходимости; новые изменения схемы оформляйте новой миграцией.

```bash
docker compose -f docker-compose.prod.yml exec api alembic current
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
docker compose -f docker-compose.prod.yml exec api alembic history
```

Для разработки:

```bash
make revision m="description"
make migrate
```

## Запуск сервисов

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml restart api
docker compose -f docker-compose.prod.yml restart bot
docker compose -f docker-compose.prod.yml restart worker
docker compose -f docker-compose.prod.yml logs -f api --tail=200
docker compose -f docker-compose.prod.yml logs -f bot --tail=200
docker compose -f docker-compose.prod.yml logs -f worker --tail=200
```

## Telegram-бот

Пользовательские команды:

```text
/start
/menu
/profile
/orders
/profit
/stocks
/analytics
/alerts
/accounts
/sync
/subscription
/settings
/low_margin
/help
```

Админские команды:

```text
/admin
/tariffs
/promocodes
/admin_reconcile_subs
/admin_fix_payment_urls
```

Админские команды и кнопки доступны только Telegram ID из `ADMIN_TELEGRAM_IDS`.
Покупка подписки запускается из меню подписки, после чего пользователь переходит на
страницу оплаты YooKassa. После успешной оплаты webhook активирует подписку, а бот
показывает обновлённый статус.

### Telegram webhook

Webhook URL собирается из `.env`:

```bash
cd /opt/mpcontrol
set -a
source .env
set +a

echo "${BOT_WEBHOOK_BASE_URL%/}${BOT_WEBHOOK_PATH}"
```

Для production ожидаемый URL:

```text
https://bot.mpcontrol.online/webhook/telegram
```

Управление webhook:

```bash
bash scripts/bot_set_webhook.sh
bash scripts/bot_get_webhook_info.sh
bash scripts/bot_delete_webhook.sh
```

Проверка Telegram:

```bash
curl -sS "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo"
```

В ответе `result.url` должен быть равен
`https://bot.mpcontrol.online/webhook/telegram`. Если задан `BOT_WEBHOOK_SECRET`,
FastAPI проверяет заголовок `X-Telegram-Bot-Api-Secret-Token`; сам secret не должен
попадать в логи.

## Web-кабинет

Основные адреса:

```text
https://example.com/web/
https://example.com/web/orders
https://example.com/web/profit
https://example.com/web/plan-fact
https://example.com/web/break-even
https://example.com/web/products
https://example.com/web/stocks
https://example.com/web/pricing
https://example.com/web/mrc-pricing
https://example.com/web/subscription
https://example.com/web/settings
```

Вход работает через одноразовый токен из Telegram-бота:

```text
https://example.com/web/login?token=...
```

После успешного входа создаётся HttpOnly session cookie.

## Админка

Web-админка:

```text
https://example.com/web/admin/tariffs
https://example.com/web/admin/promocodes
https://example.com/web/admin/commissions
https://example.com/web/admin/wb-logistics
```

Системный endpoint ошибок:

```text
https://example.com/admin/errors
```

Для `/admin/errors` требуется заголовок `X-Admin-Secret` со значением
`APP_SECRET_KEY`. Не открывайте этот endpoint публично без reverse proxy и доступа
только для администраторов.

## Тарифы

Тарифы находятся в таблицах подписок и управляются администратором. README не
фиксирует цены как истину: цены, лимиты, периоды и публичность тарифов редактируются
через web-админку и Telegram-админку.

Типовые тарифные коды:

- FREE;
- BASIC;
- PRO;
- ENTERPRISE.

## Промокоды

Промокоды поддерживают:

- процентную скидку;
- фиксированную скидку;
- бесплатные дни;
- общий лимит использований;
- срок действия;
- ограничение по тарифам;
- ограничение по периодам оплаты;
- режим только для новых пользователей;
- историю использований.

## Платежи YooKassa

Платёжный поток:

1. Пользователь выбирает тариф и период в Telegram-боте.
2. `PaymentService` создаёт платёж YooKassa и локальную запись платежа.
3. Пользователь возвращается на `/payment/success` или `/payment/cancel`.
4. YooKassa отправляет webhook на `/webhooks/yookassa`.
5. Webhook сверяет статус, обновляет платёж и активирует подписку.

Для reverse proxy с префиксом `/web` есть совместимый endpoint
`/web/webhooks/yookassa`, но канонический webhook — `/webhooks/yookassa`.

## Синхронизации WB/Ozon

Фоновые задачи описаны в `app/workers/tasks.py` и подключены в
`app/workers/settings.py`.

- новые заказы — примерно каждые 3 минуты;
- продажи и выкупы — примерно каждые 15 минут;
- FBO digest — примерно каждые 30 минут;
- backfill исторических данных — примерно каждые 10 минут;
- контроль FBS/rFBS сроков — примерно каждые 15 минут;
- low-stock alerts — 3 раза в день;
- daily reports — в час `DAILY_REPORT_HOUR`;
- WB promotions sync — по настройкам `WB_PROMOTIONS_SYNC_*`.

Ручной запуск синхронизаций доступен из Telegram-бота и страницы
`/web/accounts`, а администратору также доступен контроль запусков на
`/web/admin/sync-status`.

### Карта worker-задач

| Задача | Назначение | Расписание |
| --- | --- | --- |
| `poll_new_orders` | новые FBS/rFBS/DBS/FBO заказы и уведомления | каждые 3 минуты |
| `sync_sale_events` | продажи, выкупы, возвраты и lifecycle-уведомления | каждые 15 минут |
| `send_fbo_digests` | FBO digest | каждые 30 минут |
| `send_alert_notifications` | отправка pending alerts | каждые 5 минут |
| `process_history_backfills` | исторические backfill jobs | каждые 10 минут |
| `check_fbs_deadlines` | контроль сроков FBS/rFBS | каждые 15 минут |
| `check_low_stocks` | остатки и прогноз out-of-stock | 08:10, 14:10, 20:10 |
| `send_daily_reports` | ежедневные отчёты | `DAILY_REPORT_HOUR` |
| `sync_products` | синхронизация товаров | ежедневно |
| `sync_wb_daily_sales_reports` | WB daily sales reports | ежедневно |
| `sync_wb_daily_financial_details` | WB finance v1 details | ежедневно |
| `sync_wb_daily_promotions` | WB promotions/nomenclatures | каждые 30 минут |
| `sync_wb_product_prices` | текущие цены WB | каждые 30 минут |
| `check_auto_promo_prices` | рекомендации и автоцены WB | каждые 30 минут |
| `reconcile_pending_payments` | сверка pending платежей YooKassa | каждые 20 минут |

Каждый запуск пишется в `sync_task_runs`: `started_at`, `finished_at`,
`duration_ms`, `records_processed`, `success_count`, `failed_count`, `last_error`.
Администратор может быстро проверить ключевые worker-задачи на
`/web/admin/worker-diagnostics`: `poll_new_orders`, `sync_sale_events`,
`sync_wb_product_prices`, `check_auto_promo_prices`.

## Web/admin карта

- `/web/admin/users` — список пользователей.
- `/web/admin/users/{id}` — карточка пользователя, кабинеты WB/Ozon, последние
  заказы, платежи, ошибки, уведомления и audit log.
- `/web/admin/payments` — платежи, фильтры и ручная проверка статуса YooKassa.
- `/web/admin/notifications` — события уведомлений и повторная постановка в retry.
- `/web/admin/sync-status` — состояние фоновых задач и ручной запуск ключевых sync.
- `/web/admin/worker-diagnostics` — последние запуски и счётчики ключевых worker-задач.
- `/web/admin/audit-log` — журнал действий.
- `/web/admin/tariffs` — тарифы.
- `/web/admin/promocodes` — промокоды.
- `/web/admin/commissions` — комиссии WB/Ozon.
- `/web/admin/wb-logistics` — логистика WB, если роут включён в приложении.

## Feature flags

Единая проверка доступа живёт в `app/services/subscriptions/feature_access_service.py`
и совместимом `app/services/feature_access_service.py`.

Коды функций:

- `web_dashboard`
- `advanced_analytics`
- `plan_fact`
- `break_even`
- `stock_forecast`
- `alerts`
- `api_access`
- `auto_promotions`
- `mrc_pricing`
- `price_management`

Флаги хранятся в `subscription_tiers`: `feature_web_cabinet`,
`feature_analytics`, `feature_plan_fact`, `feature_break_even`,
`feature_stock_forecast`, `feature_alerts`, `feature_api_access`,
`feature_mrc_pricing`, `feature_auto_promotions`.

## Audit log

Важные действия пишутся в `audit_logs`: изменение тарифа, создание и применение
промокода, создание и успех платежа, активация подписки, обновление МРЦ,
применение цены WB, запуск синхронизации, добавление и удаление кабинета.

Пользовательская диагностика кабинета доступна на `/web/health`.

## Troubleshooting уведомлений заказов

1. Проверьте, что `worker` запущен и `poll_new_orders` есть в `/web/admin/sync-status`.
2. Проверьте `notifications_enabled` пользователя и настройки кабинета в `/web/settings`.
3. Проверьте, что Redis доступен: `docker compose -f docker-compose.prod.yml exec redis redis-cli ping`.
4. Проверьте логи:

```bash
docker compose -f docker-compose.prod.yml logs worker --tail=200
docker compose -f docker-compose.prod.yml logs bot --tail=200
```

5. Если Telegram вернул permanent error, проверьте, не заблокировал ли пользователь бота.

## Troubleshooting YooKassa

1. Проверьте `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`, `YOOKASSA_RETURN_URL` и
   `YOOKASSA_WEBHOOK_URL`.
2. Канонический webhook: `/webhooks/yookassa`; reverse-proxy совместимый путь:
   `/web/webhooks/yookassa`.
3. В личном кабинете YooKassa webhook не должен быть настроен на корень сайта `/`.
   POST `/` в access-log обычно означает ошибочную настройку URL.
4. Pending платежи сверяются задачей `reconcile_pending_payments`.
5. В `/web/admin/payments` можно вручную проверить статус платежа через YooKassa.
6. Повторная активация подписки защищена статусом платежа и
   `subscription_applied_at`.

## Troubleshooting WB автоакций и МРЦ

1. У товара должен быть задан МРЦ. Автоизменение без МРЦ запрещено.
2. Цена входа не применяется ниже `minPrice`.
3. Сервис не меняет `minPrice` в WB, отправляется только цена и скидка.
4. Автоизменение блокируется при риске карантина WB: новая цена в 3+ раза ниже текущей.
5. Условия автоакции лучше загружать через импорт: так рекомендация привязывается к
   конкретной акции, а `required_price_source` сохраняет источник цены входа.
6. После отправки цены статусы проходят цепочку:
   `price_sent_to_wb` → `price_accepted_by_wb` → `waiting_promotion_join` →
   `promotion_joined` или `promotion_not_joined`.

## Логи

Логи пишутся в Docker stdout/stderr и в локальную директорию `logs/`.
Чувствительные query-параметры и заголовки маскируются в web logging middleware.

```bash
docker compose -f docker-compose.prod.yml logs -f api bot --tail=200
docker compose -f docker-compose.prod.yml logs -f worker --tail=200
tail -n 200 logs/app.log
tail -n 200 logs/errors.log
```

`/health` исключён из обычного INFO access-log. Он логируется только при
HTTP-статусе `>= 400` или длительности больше `1000 ms`.

Скрипты деплоя пишут логи в `DEPLOY_LOG_DIR`.

## Типовые команды обслуживания

```bash
cd /opt/example-app

git status
git pull

docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml exec api alembic current
docker compose -f docker-compose.prod.yml exec api alembic upgrade head

docker compose -f docker-compose.prod.yml restart api bot worker
docker compose -f docker-compose.prod.yml logs -f api bot worker --tail=200
```

Диагностика неожиданных рестартов и OOMKilled:

```bash
docker compose -f docker-compose.prod.yml ps
docker inspect --format '{{.Name}} RestartCount={{.RestartCount}} OOMKilled={{.State.OOMKilled}} ExitCode={{.State.ExitCode}} Error={{.State.Error}} FinishedAt={{.State.FinishedAt}}' $(docker compose -f docker-compose.prod.yml ps -q api bot worker)
docker compose -f docker-compose.prod.yml logs api bot worker --tail=300
```

Проверка worker-run событий и web-auth индексов:

```bash
docker compose -f docker-compose.prod.yml exec postgres sh -lc "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -c \"select task_name, status, started_at, finished_at, duration_ms, success_count, failed_count, left(coalesce(last_error, ''), 500) as last_error from sync_task_runs order by started_at desc limit 50;\""
docker compose -f docker-compose.prod.yml exec postgres sh -lc "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -c \"select tablename, indexname, indexdef from pg_indexes where tablename in ('one_time_login_tokens', 'user_web_sessions') order by tablename, indexname;\""
```

## Деплой

Скрипты находятся в `deploy/`:

- `deploy/install.sh` — первичная установка сервера;
- `deploy/update.sh` — обновление кода, backup БД, миграции и restart сервисов;
- `deploy/backup.sh` — ручной backup PostgreSQL;
- `deploy/nginx/mpcontrol.conf.template` — nginx template;
- `deploy/nginx/bot.mpcontrol.online.conf` — отдельный nginx config для Telegram webhook;
- `deploy/systemd/` — templates для безопасного Telegram-trigger деплоя.

Перед крупными миграциями делайте backup БД.

## Безопасность

- не храните `.env` и реальные секреты в Git;
- используйте `.env.example` только как безопасный шаблон;
- шифруйте marketplace credentials через `ENCRYPTION_KEY`;
- не логируйте токены, пароли, API-ключи и cookie;
- ограничивайте web-админку и Telegram-админку списком `ADMIN_TELEGRAM_IDS`;
- защищайте `/admin/errors` заголовком `X-Admin-Secret` и reverse proxy;
- проверяйте YooKassa webhook и обрабатывайте его идемпотентно;
- делайте backup БД перед крупными миграциями и деплоем;
- не публикуйте реальные домены, token, password, secret key и банковские данные.

## Проверка после деплоя

1. Проверить Docker-сервисы.
2. Проверить текущую миграцию Alembic.
3. Открыть web-кабинет.
4. Проверить вход через Telegram token.
5. Проверить Telegram-бота и `/start`.
6. Проверить web-админку тарифов и промокодов.
7. Проверить создание платежа и return URL YooKassa.
8. Проверить webhook YooKassa на тестовом платеже.
9. Проверить Telegram webhook на `https://bot.mpcontrol.online/webhook/telegram`.
10. Проверить ручную синхронизацию WB/Ozon.
11. Проверить логи `api`, `bot` и `worker`.

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml exec api alembic current
curl -I https://bot.mpcontrol.online/health
curl -I https://bot.mpcontrol.online/webhook/telegram
docker compose -f docker-compose.prod.yml logs -f api bot worker --tail=200
```

## Разработка

```bash
make install
make lint
make format
make test
```

Тесты:

```bash
pytest
pytest tests/unit/
pytest tests/integration/
pytest -k "test_profit"
```

## Официальные ссылки

- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Wildberries API](https://dev.wildberries.ru/)
- [Ozon Seller API](https://docs.ozon.ru/api/seller/)
- [YooKassa](https://yookassa.ru/developers)
