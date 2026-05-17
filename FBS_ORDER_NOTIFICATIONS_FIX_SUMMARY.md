# version: 1.0.0
# description: Summary of FBS order notification production fix and related regressions.
# updated: 2026-05-17

# FBS Order Notifications Fix Summary

## Исходная проблема

Telegram-бот не присылал уведомления о новых FBS-заказах. Аудит прошёл всю цепочку:

1. marketplace API;
2. polling/sync;
3. нормализация заказа;
4. сохранение в БД;
5. определение нового или duplicate-заказа;
6. подготовка карточки;
7. отправка в Telegram;
8. отметка `first_notified_at`.

## Root Cause

Для Wildberries новые FBS-заказы уже забирались через `/api/v3/orders/new`.

Для Ozon polling использовал только `/v3/posting/fbs/list` за короткое окно последних 30 минут.
FBS-заказы, которые находятся в рабочем списке продавца и требуют сборки, могут приходить через
`/v3/posting/fbs/unfulfilled/list`. Этот endpoint в `poll_new_orders` не использовался, поэтому
часть новых Ozon FBS-заказов не попадала в нормализацию и не доходила до Telegram-уведомлений.

Дополнительный риск был в доставке с фото: если `send_photo` падал из-за изображения или Telegram
media validation, сообщение не пробовало уйти текстом. При этом архитектурно заказ не помечался
доставленным до успешного `send_message/send_photo`, поэтому retry был возможен, но первый пользовательский
контакт мог срываться из-за необязательной картинки.

## Что изменено

- Ozon FBS polling теперь объединяет:
  - `/v3/posting/fbs/list`;
  - `/v3/posting/fbs/unfulfilled/list`.
- Дубликаты между двумя Ozon endpoint удаляются по `posting_number`.
- WB FBS polling сохранён через `/api/v3/orders/new`.
- Сохранение заказа и успешная доставка уведомления остаются разными состояниями:
  - заказ сохраняется в `orders`;
  - успешная отправка отмечается только через `OrderRepository.mark_notified()`;
  - если отправка упала, `first_notified_at` остаётся пустым;
  - следующий polling duplicate-заказа повторно готовит уведомление.
- `NotificationService.send_new_order()` теперь пробует отправить текстовое сообщение, если отправка
  фото не удалась.
- Ошибка текстовой отправки пробрасывается дальше, чтобы worker не пометил заказ доставленным.

## Логирование

Добавлены или усилены структурированные события:

- `fbs_order_polled`;
- `fbs_order_normalized`;
- `fbs_order_detected_as_new`;
- `fbs_order_persisted`;
- `fbs_order_notification_prepared`;
- `fbs_order_notification_sent`;
- `fbs_order_notification_failed`;
- `fbs_order_notification_retry_scheduled`;
- `fbs_order_duplicate_skipped`;
- `fbs_order_duplicate_with_unsent_notification_requeued`.

По этим логам можно понять, на каком этапе находится конкретный FBS-заказ.

## Дополнительные production-ошибки

### Исправлена ошибка ERR_TOO_MANY_REDIRECTS в WEB-кабинете

Проблемный URL: `/web/accounts`. Такой же риск был у внутренних страниц:

- `/web/profile`;
- `/web/subscription`;
- `/web/orders`;
- `/web/products`;
- `/web/profit`;
- `/web/costs`;
- `/web/settings`.

Фактическая redirect-chain при production reverse proxy:

```text
GET https://app.mpcontrol.online/web/accounts
→ upstream path /web/web/accounts
→ 308 Location: /web/accounts
→ GET https://app.mpcontrol.online/web/accounts
→ upstream path /web/web/accounts
→ 308 Location: /web/accounts
→ ...
```

Root cause: compatibility-route `/web/web/{section}` после последнего фикса стал редиректить на
canonical `/web/{section}`. Это корректно для прямой старой ссылки, но создаёт цикл, если reverse
proxy уже добавляет `/web` к upstream path.

Исправление:

- legacy GET `/web/web/{section}` больше не делает redirect;
- route снова обслуживает canonical WEB-страницу внутренне;
- штатная HTML-навигация при этом остаётся canonical и не генерирует `/web/web/...`;
- неавторизованный `/web/accounts` возвращает 401-страницу без redirect loop;
- trailing slash `/web/accounts/` проверен на отсутствие цикла.

Добавлены regression-тесты:

- login cookie открывает `/web/accounts`, `/web/profile`, `/web/subscription`, `/web/orders`,
  `/web/products`, `/web/profit`, `/web/costs`, `/web/settings`;
- unauthorized `/web/accounts` не уходит в loop;
- `/web/accounts` и `/web/accounts/` имеют не больше одного redirect;
- legacy `/web/web/sales` обслуживается без redirect loop.

### Двойной WEB-префикс `/web/web/...`

Штатный HTML WEB-кабинета проверен тестами на отсутствие `href="/web/web/..."`
и `action="/web/web/..."`. Compatibility-route `/web/web/*` оставлен для старых ссылок
и reverse proxy, который добавляет `/web` при upstream-проксировании. Legacy GET теперь не
редиректит, чтобы не создавать цикл; legacy POST себестоимости временно поддержан для уже
открытых вкладок.

### `created_at = NULL` при ручном назначении тарифа

Production падал при `SubscriptionService.assign_admin_subscription()` из-за `NOT NULL`
на `user_subscriptions.created_at`: ранняя миграция создала timestamp-колонки без server default.

Исправление:

- `create_subscription()` и `assign_admin_subscription()` явно заполняют `created_at` и `updated_at`;
- добавлена migration `20260517_0015_subscription_timestamp_defaults`;
- migration backfill-ит NULL timestamps и ставит server defaults для:
  - `subscription_tiers`;
  - `user_subscriptions`;
  - `payments`.

### INFO-логи доменов

- `app.mpcontrol.online/web/` без session cookie должен возвращать 401.
- `api.mpcontrol.online/` и `bot.mpcontrol.online/` с 404 на корне не являются причиной
  FBS-проблемы. Их можно оставить как есть, если отдельный health/landing endpoint не требуется.

## Тесты

Добавлены и обновлены regression-тесты:

- WB FBS новый заказ готовит уведомление и не помечается доставленным до Telegram send;
- Ozon FBS duplicate без `first_notified_at` повторно готовит уведомление;
- Ozon `fbs/list` + `fbs/unfulfilled/list` объединяются и дедуплицируются;
- уже уведомлённый FBS duplicate не отправляется повторно;
- ошибка построения карточки не помечает заказ уведомлённым;
- `send_photo` fallback отправляет текст;
- ошибка `send_message` пробрасывается для retry;
- админское назначение BASIC/PRO/ENTERPRISE создаёт timestamp-поля.

## Проверка после деплоя

На production нужно выполнить:

```bash
docker compose exec api alembic upgrade head
docker compose logs -f worker | grep -E "fbs_order_|new_order_notification_"
```

При новом Ozon FBS-заказе ожидаемая цепочка:

1. `fbs_order_polled`;
2. `fbs_order_normalized`;
3. `fbs_order_detected_as_new`;
4. `fbs_order_persisted`;
5. `fbs_order_notification_prepared`;
6. `fbs_order_notification_sent`.

Если Telegram временно недоступен:

1. `fbs_order_notification_failed`;
2. `fbs_order_notification_retry_scheduled`;
3. на следующем polling `fbs_order_duplicate_with_unsent_notification_requeued`.
