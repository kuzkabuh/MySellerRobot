# Changelog

## 1.14.0

### Added

- Telegram-уведомления о начале и завершении синхронизаций (старт, успех, предупреждение, ошибка).
- Watchdog для зависших запусков: запуски со статусом "running" дольше 2 ч (6 ч для backfill) автоматически помечаются как "Превышено время".
- Автообновление страницы "История запусков" каждые 15 сек, если есть активные задачи.
- Служба `SyncNotificationService` для отправки уведомлений пользователю и администраторам.
- Методы `mark_warning()`, `mark_timeout()`, `finish_run()`, `mark_stale_syncs_as_failed()` в `WebSyncRunService`.
- Статусы "Предупреждение", "Превышено время", "Отменено", "Ожидает" на странице истории запусков.
- Отображение колонки "Обновлено" в истории запусков.

### Fixed

- **Критическое**: задачи из "Центра синхронизации" навсегда оставались в статусе "Выполняется", т.к. `_tracked_task` не обновлял `SyncRun`. Теперь `_tracked_task` обновляет и `SyncRun`, и `SyncTaskRun`.
- Исправлена передача `sync_run_id` от `trigger_sync()` в arq-воркер и обратно в `WebSyncRunService.mark_success/mark_failed`.
- При ошибке воркера статус `SyncRun` теперь корректно меняется на "Ошибка".
- Во всех статусах заполняются поля `finished_at`, `duration_seconds`, счётчики записей.
- При открытии страницы синхронизации запускается очистка зависших запусков.

## 1.13.0

### Added

- Улучшен раздел "Заказы" в веб-интерфейсе:
  - Добавлена сводка по заказам (заказы, выручка, прибыль, маржа, проблемные).
  - Убрано дублирование навигации — единые вкладки: Заказы / Продажи / Возвраты / Прибыль / План/факт.
  - Добавлены быстрые периоды: Сегодня, Вчера, 7 дней, 30 дней, Этот месяц, Прошлый месяц.
  - Улучшена таблица заказов с раскрытием деталей строки.
  - Добавлены кнопки "Подробнее" в каждую строку.
  - Добавлено отображение статуса экономики (Факт / Оценка / План) в таблице.
  - Добавлены бейджи проблемных заказов (нет себестоимости, убыток, неоднозначное сопоставление).
  - Улучшен индикатор синхронизации с указанием последнего обновления и ссылкой на Центр синхронизации.
  - Добавлен экспорт в CSV (параметр export=csv).
  - Улучшена пагинация с кнопками первая/последняя страница.
  - Улучшены пустые состояния с рекомендациями действий.
  - Улучшена мобильная адаптивность таблицы.
- Добавлен фильтр экономики "Без фин. данных".
- Добавлено поле `srid` в OrderRow для корректного отображения идентификаторов.
- Добавлены функции `_marketplace_id_label`, `_marketplace_posting_label`, `_order_identifiers` для корректных подписей WB/Ozon.

### Fixed

- Исправлено отображение "Заказ WB" для заказов Ozon — теперь отображается "Заказ Ozon".
- Исправлены подписи источников:
  - "Событие отправления Ozon" → "API Ozon: отправление"
  - "Онлайн-заказ WB" → "API WB: заказ"
  - "Заказ из отчёта WB" → "Файл отчёта WB"
  - "FBO-заказ" → "API Ozon: заказ"
- Исправлено отображение плановой/фактической прибыли в карточке заказа.
- Добавлено сообщение "Финансовые данные по этому заказу ещё не загружены" при отсутствии фин. данных.

## 1.12.0

### Added

- Полностью переработан раздел «Центр синхронизации»:
  - Вкладки: Обзор, Синхронизация, Ошибки, История запусков, Настройки.
  - Ручной запуск синхронизаций WB/Ozon для каждого кабинета.
  - Проверка API-ключей с обратной связью для пользователя.
  - История запусков SyncRun с фильтрацией по статусу.
  - Диагностика ошибок с человекочитаемыми сообщениями.
  - Защита от повторного запуска (проверка running/queued).
  - Автообновление статуса задачи через polling (fetch + setInterval).
  - Тосты/уведомления о результатах синхронизации.
  - Кнопки: «Повторить просроченные», «Повторить ошибки» (админ).
  - Read-only раздел «Настройки автообновления».
- Добавлена модель SyncRun (таблица `sync_runs`) для учёта запусков.
- Добавлен сервис WebSyncRunService для управления синхронизациями.
- Добавлены backend endpoints:
  - `POST /web/sync-center/accounts/{id}/run` — запуск синхронизации.
  - `POST /web/sync-center/accounts/{id}/verify-api-key` — проверка ключа.
  - `GET /web/sync-center/runs/{id}/status` — статус запуска.
  - `GET /web/sync-center/history` — история запусков (JSON).
- Добавлена миграция `20260610_0064_add_sync_run_model.py`.

### Changed

- Название раздела в сайдбаре: «Синхронизация» → «Центр синхронизации».
- Весь UI-текст раздела переведён на русский язык.
- Улучшена логика определения просроченных синхронизаций.
- Версия проекта обновлена до 1.12.0.

## 1.9.10

### Security

- Добавлена централизованная Origin/Referer-защита state-changing web-запросов
  `/web/*` без применения к API/webhook routes.
- YooKassa и Telegram webhooks переведены из fail-open в fail-closed режим:
  production требует настроенный секрет, dev-insecure режим включается только явно.
- Forwarded IP headers теперь учитываются только от доверенных proxy networks.

### Fixed

- POST-мутации платных разделов План/факт и МРЦ дополнительно проверяют backend
  feature access, а не полагаются только на UI.
- Telegram user menu больше не использует Telegram ID как внутренний `users.id`
  при проверке API-ключей и обновлении профиля.
- Профиль показывает актуальный тариф из `SubscriptionService`, а не legacy
  `users.tariff`.
- Настройки уведомлений для кабинета наследуют global-настройки пользователя и
  могут переопределять их по типам.
- Оплаченный YooKassa payment с ошибкой активации подписки переводится в
  диагностируемый `FAILED`, а не в `SUCCEEDED` без тарифа.

### Changed

- Runtime baseline закреплён на Python 3.12: `pyproject.toml`, Docker image,
  developer tooling и документация теперь согласованы с 3.12.
- Корневой FastAPI route отдаёт `public/index.html` как единый источник landing page.
- Админский ручной запуск sync-задач ставит arq job в очередь вместо прямого
  выполнения worker-функции в web request.
- Production backup требует шифрование файлового архива с `.env`, если риск
  plaintext-секретов не подтверждён явно.
- Добавлен production logrotate-конфиг для 48-часового окна file logs.

### Added

- Миграция `20260607_0057` добавляет partial unique indexes для global/account
  notification settings.
- Добавлены regression-тесты для web Origin guard, webhook fail-closed, trusted
  proxy IP, feature gates, Telegram ID mapping, notification inheritance,
  payment activation failures и public/deploy hardening.

## 1.9.8

### Fixed

- Добавлена миграция для `user_activity_logs.updated_at`, чтобы страница
  `/web/settings/security` открывалась без 500-ошибки при чтении истории
  действий пользователя.

## 1.9.7

### Fixed

- Web-вход по паролю приведён к требованиям безопасности: логин 3-50 символов,
  вход доступен по логину, email или Telegram ID, а при смене пароля требуется
  текущий пароль.
- Добавлена простая защита POST `/web/login` от перебора пароля по IP и логину.
- Production-примеры доменов синхронизированы: API использует
  `https://api.mpcontrol.online`, Telegram webhook — `https://bot.mpcontrol.online`.

## 1.9.6

### Fixed

- Единая логика определения текущего тарифа закреплена в `SubscriptionService`.
- `FeatureAccessService` теперь использует тот же источник тарифа, что web и Telegram.
- При нескольких активных подписках выбирается тариф с наибольшим приоритетом и пишется warning.
- Поиск тарифов по коду стал нечувствительным к регистру.
- Добавлены тесты защиты от сценария, когда активный PRO отображается или проверяется как Free.

## 1.9.5

### Added

- Добавлена адаптивная публичная главная страница `public/index.html` для
  `mpcontrol.online` с отдельными CSS/JS ассетами, SEO/meta/OG-тегами,
  favicon, manifest, robots.txt и sitemap.xml.
- Публичная страница согласована с доменной схемой проекта: лендинг на
  `mpcontrol.online`, web-кабинет на `app.mpcontrol.online`, Telegram-бот через
  `https://t.me/mpcontrolrobot`.

### Changed

- Nginx-шаблон для публичного сайта отдаёт HTML без кэша и статические ассеты с
  cache headers.
- Production installer больше не затирает существующий `public/index.html`
  стартовой заглушкой.
- Версия проекта обновлена до 1.9.5.

## 1.9.4

### Fixed

- Production installer now includes `bot.mpcontrol.online` in the SSL certificate
  domain flow, treats the bot webhook domain as critical during DNS validation, and
  verifies that the issued certificate SAN contains `DNS:bot.mpcontrol.online`.
- Installer diagnostics now print Certbot certificate details, the bot certificate
  SAN, and Telegram `getWebhookInfo` after webhook setup.

## 1.9.3

### Changed

- Refactor production deployment and stability layer:
  - fixed Alembic version table length for long revision IDs;
  - added Fernet ENCRYPTION_KEY validation;
  - improved production install.sh;
  - added automatic PostgreSQL and config backups;
  - added backup restore scripts;
  - improved Docker, Nginx, SSL and webhook diagnostics;
  - improved logs and diagnostics;
  - audited subscriptions, admin panel, marketplace sync, promotions and pricing logic.

## 1.9.2

### Fixed

- Исправлено падение production-установщика на чистой PostgreSQL базе из-за
  длинных Alembic revision id. Таблица `alembic_version` теперь заранее
  создаётся/обновляется с `version_num VARCHAR(255)` перед запуском миграций.

### Changed

- Версия проекта обновлена до 1.9.2.

## 1.9.1

### Added

- Добавлена загрузка данных компании/ИП по ИНН через DaData в web-настройках.
- Добавлена таблица `user_company_profiles` для сохранения реквизитов пользователя.
- Добавлена вкладка `/web/settings/company` с предпросмотром, сохранением, обновлением и очисткой данных компании.
- В карточку пользователя в админке добавлен блок «Данные компании».
- Добавлены env-переменные `DADATA_API_KEY`, `DADATA_SECRET_KEY`, `DADATA_BASE_URL`.
- Добавлен ежедневный backup PostgreSQL БД и важных файлов проекта.
- Добавлены systemd service/timer для автоматического backup.
- Добавлена документация восстановления `docs/BACKUP_RESTORE.md`.
- Добавлен админский раздел `/web/admin/backups` со статусом backup.

### Changed

- Версия проекта обновлена до 1.9.1.

## 1.8.3

### Changed

- Production Docker image no longer installs dev dependencies by default.
- Playwright/Chromium browser fallback is optional for production builds.
- Added `.dockerignore` to keep Git metadata, local env files, logs, runtime files, backups,
  Python caches and build artifacts out of Docker context.
- Order polling cron now derives its minute schedule from `ORDER_POLL_INTERVAL_SECONDS`.
- `/web/break-even` checks `FeatureCode.BREAK_EVEN`.
- Web session reads no longer perform an implicit commit in `current_web_user()`.
- FREE tier lookup and active subscription status checks are case-insensitive.

### Fixed

- Ruff violations in the latest Alembic migrations.
- Web route facade no longer uses wildcard imports.

## 1.8.2

### Added

- Добавлены `audit_logs`, `sync_task_runs`, `notification_events`.
- Добавлены web/admin страницы пользователей, платежей, уведомлений, audit log и sync status.
- Добавлен пользовательский экран `/web/health`.
- Добавлен единый `FeatureAccessService.can_use(user_id, feature_code)`.

### Changed

- WB auto promo рекомендации учитывают МРЦ, minPrice, источник `required_price` и риск карантина WB.
- Платежи YooKassa получили `subscription_applied_at` для видимости и защиты от повторного начисления.
- Worker-задачи пишут состояние запусков в `sync_task_runs`.

### Docs

- README обновлён под 1.8.2: worker map, web/admin map, feature flags и troubleshooting.

## 1.8.1

### Added

- Документирована работа тарифов.
- Документирована работа промокодов.
- Документирована Telegram-админка.
- Документирована web-админка.
- Добавлено описание платежей YooKassa.
- Добавлено описание аудита и диагностики действий пользователей.

### Changed

- README.md приведён к актуальной структуре проекта.
- Версия проекта обновлена до 1.8.1.
- Обновлены команды запуска, миграций, логов и обслуживания.
- `.env.example` очищен от публичных доменов проекта и приведён к безопасным example-значениям.

### Security

- Из документации удалены реальные домены, секреты, токены, пароли и чувствительные данные.
