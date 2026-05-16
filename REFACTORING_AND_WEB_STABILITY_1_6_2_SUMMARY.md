# version: 1.0.0
# description: Stabilization report for WEB login regression and safe refactoring in 1.6.2.
# updated: 2026-05-17

# WEB stability and refactoring summary 1.6.2

## Исходная проблема

После расширения WEB-кабинета переход из Telegram-бота по одноразовой WEB-ссылке начал
возвращать `Internal Server Error`. До расширения WEB-слоя вход через `/web/login?token=...`
работал корректно.

## Root cause

Ошибка находилась в цепочке:

- `app/web/routes.py::dashboard`;
- `app/services/web_cabinet_service.py::subscription_page`;
- `app/services/web_cabinet_service.py::accounts_page`;
- `app/services/subscription_service.py::get_user_tier`.

После WEB-рефакторинга главная страница стала показывать приветственный блок с текущим тарифом и
лимитами кабинетов. Для этого dashboard начал вызывать `WebCabinetService.subscription_page()` и
`WebCabinetService.accounts_page()`. Оба метода запрашивают текущий тариф через
`SubscriptionService.get_user_tier()`.

Для FREE-пользователя без активной подписки сервис искал строку `free` в `subscription_tiers`.
Если каталог тарифов в БД ещё не был заполнен или seed/migration не выполнились, метод поднимал:

```text
ValueError: FREE tier not found in database
```

До расширения WEB главная страница не обращалась к подписочной модели во время первого рендера,
поэтому дефект не проявлялся при открытии Telegram-ссылки.

## Исправление

В `SubscriptionService.get_user_tier()` добавлен безопасный fallback для FREE-тарифа:

- если у пользователя нет активной подписки;
- и в БД не найдена строка `subscription_tiers.code = "free"`;
- сервис возвращает read-only `SubscriptionTier` со значениями FREE по умолчанию;
- событие логируется как `free_tier_missing_using_safe_fallback`.

Это не заменяет миграции и seed-данные. Production-БД всё равно должна содержать полный каталог
тарифов. Fallback нужен, чтобы WEB-кабинет не отдавал 500 обычному FREE-пользователю.

## Дополнительный безопасный рефакторинг

В `SubscriptionService.check_account_limit()` убрано обращение к `len(user.accounts)`. Такой код
мог провоцировать async lazy-loading проблемы в SQLAlchemy. Теперь количество активных кабинетов
считается отдельным SQL-запросом по `MarketplaceAccount`.

## Тестовая защита

Добавлены тесты:

- `tests/integration/test_api_smoke.py::test_web_login_token_flow_renders_empty_free_dashboard`
  проверяет полный HTTP flow: `/web/login?token=...` → session cookie → redirect на `/web/` →
  успешный рендер главной страницы для FREE-пользователя без подписки, кабинетов и данных;
- `tests/unit/test_subscription_service_stability.py::test_get_user_tier_uses_safe_free_fallback_when_catalog_missing`
  проверяет fallback FREE-тарифа при пустом каталоге;
- `tests/unit/test_subscription_service_stability.py::test_check_account_limit_counts_accounts_without_lazy_relationships`
  проверяет, что лимит кабинетов считается без lazy relationship.

## WEB smoke coverage

В smoke-тестах проверяется регистрация основных WEB-маршрутов:

- `/web/`;
- `/web/orders`;
- `/web/sales`;
- `/web/returns`;
- `/web/profit`;
- `/web/plan-fact`;
- `/web/break-even`;
- `/web/products`;
- `/web/product-matching`;
- `/web/costs`;
- `/web/stocks`;
- `/web/alerts`;
- `/web/analytics`;
- `/web/control`;
- `/web/data-quality`;
- `/web/profile`;
- `/web/subscription`;
- `/web/accounts`;
- `/web/settings`.

Также есть unit-проверки, что ключевые WEB-рендеры не возвращают старую заглушку
`Раздел подготовлен...` и безопасно экранируют внешние значения.

## Документация

Обновлены:

- `README.md` — добавлен блок `WEB stability fix 1.6.2`;
- `DEPLOYMENT_CHECKLIST.md` — добавлена обязательная проверка Telegram WEB login flow и контроль
  наличия FREE-тарифа в `subscription_tiers`.

## Что осталось контролировать

- После деплоя warning `free_tier_missing_using_safe_fallback` не должен становиться нормой. Если
  он появляется в production-логах, нужно проверить миграции и seed каталога тарифов.
- При дальнейшем расширении WEB-кабинета новые страницы должны проверяться через smoke-тесты на
  пользователя без данных: без кабинетов, заказов, товаров, платежей и активной подписки.
