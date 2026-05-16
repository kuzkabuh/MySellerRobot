# version: 1.0.0
# description: Release notes for subscription lifecycle stage 1.6.3.
# updated: 2026-05-17

# Release 1.6.3 — жизненный цикл подписок

## Цель

Релиз `1.6.3` завершает бизнес-корректный базовый lifecycle подписок:
`monthly` / `yearly`, trial, expiration и upgrade без возврата к старым моделям
`SubscriptionPlan` / `Subscription`.

## Что сделано

- Версия проекта повышена до `1.6.3` в `VERSION`, `pyproject.toml` и FastAPI metadata.
- В `UserSubscription` добавлено поле `period`.
- В `SubscriptionStatus` добавлен статус `REPLACED` для upgrade-сценариев.
- `SubscriptionService.get_active_subscription()` теперь считает активными `ACTIVE` и `TRIAL`,
  но не возвращает записи с истёкшим `expires_at`.
- `SubscriptionService.create_subscription()` принимает явный `period`.
- `monthly` создаёт период 30 дней, `yearly` — 365 дней.
- При повторной оплате того же тарифа подписка продлевается от текущего `expires_at`, если он ещё
  не истёк.
- При продлении истёкшей подписки новый срок считается от текущего времени.
- Upgrade BASIC → PRO переводит старую активную подписку в `REPLACED` и создаёт новую активную
  PRO-подписку.
- Trial PRO на 14 дней создаётся через `start_trial()` и доступен пользователю только один раз.
- Добавлен `expire_outdated_subscriptions()` для перевода истёкших ACTIVE/TRIAL подписок в
  `EXPIRED`.
- `PaymentService` передаёт `period` в подписочный сервис и больше не продлевает любой активный
  тариф вслепую.

## Изменённые файлы

- `VERSION`
- `pyproject.toml`
- `app/api/main.py`
- `app/models/enums.py`
- `app/models/subscriptions.py`
- `app/services/payment_service.py`
- `app/services/subscription_service.py`
- `tests/integration/test_api_smoke.py`
- `tests/unit/test_subscription_lifecycle_163.py`
- `README.md`
- `DEPLOYMENT_CHECKLIST.md`

## Миграции

Добавлена миграция:

- `migrations/versions/20260517_0013_subscription_lifecycle.py`

Она добавляет:

- `user_subscriptions.period`;
- значение `REPLACED` в PostgreSQL enum `subscriptionstatus`.

## Тесты

Добавлены unit-тесты для:

- monthly = 30 дней;
- yearly = 365 дней;
- продление до окончания текущей подписки;
- продление после истечения;
- upgrade BASIC → PRO;
- one-time trial;
- возврат на FREE при отсутствии активной подписки;
- массовое истечение ACTIVE/TRIAL подписок.

Обновлён smoke-тест FastAPI версии на `1.6.3`.

## Закрытые риски

- Оплата yearly больше не превращается в месячную подписку.
- Повторная оплата текущего тарифа больше не теряет остаток оплаченного периода.
- Trial больше не выдаётся повторно одному пользователю.
- Истёкшие paid/trial подписки не дают платный доступ.
- Upgrade не оставляет старую BASIC-подписку активной рядом с новой PRO.

## Что дальше

Следующий этап `1.6.4` должен унифицировать runtime feature gating вокруг
`SubscriptionTier` / `UserSubscription` / `Payment` и убрать зависимость проверок доступа от старой
подписочной модели.
