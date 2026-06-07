# Changelog

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
