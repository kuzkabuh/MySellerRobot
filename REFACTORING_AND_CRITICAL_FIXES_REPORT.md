# version: 1.0.0
# description: Critical fixes and refactoring report for FBS notifications and WEB stability.
# updated: 2026-05-17

# Refactoring and Critical Fixes Report

## Исходные проблемы

Проверялись две критичные регрессии:

- Telegram-бот не присылал уведомления о новых FBS-заказах;
- WEB-кабинет на production возвращал `Internal Server Error` при переходе из Telegram.

Локальный regression flow `/web/login?token=...` → session cookie → `/web/` воспроизводимо
проходит, поэтому WEB-проблема дополнительно рассмотрена как production-разница: миграции,
старый контейнер, schema drift, env/reverse proxy/cookie.

## Root Cause FBS-уведомлений

В `OrderProcessingService.poll_account_with_stats()` заказ помечался как уведомлённый до
фактической отправки сообщения в Telegram worker’ом.

Из-за этого возникал опасный сценарий:

1. заказ был сохранён;
2. карточка или отправка уведомления падала;
3. `first_notified_at` уже мог быть выставлен или повторная попытка не формировалась;
4. следующий polling видел заказ как duplicate и не создавал уведомление повторно.

Для FBS это особенно заметно, потому что пользователь ожидает моментальное сообщение, а не FBO
digest.

## Что исправлено для FBS

- `OrderProcessingService` больше не вызывает `mark_notified()` до отправки;
- worker помечает заказ уведомлённым только после успешного `NotificationService.send_new_order()`;
- для уже сохранённых FBS/rFBS/DBS/DBW заказов с пустым `first_notified_at` добавлена повторная
  подготовка уведомления при следующем polling;
- повторно уведомлённые заказы с заполненным `first_notified_at` не дублируются;
- в `NewOrderNotification` добавлен контекст для структурированных логов:
  `user_id`, `account_id`, `sale_model`, `fulfillment_type`, `event_type`;
- worker логирует `new_order_notification_sent` и `new_order_notification_send_failed` с
  marketplace, fulfillment type, order id, user id и event type.

## WEB Internal Server Error

Локально сценарий авторизации через Telegram-ссылку остаётся зелёным:

- `/web/login?token=valid-token` возвращает redirect;
- выставляется session cookie;
- `/web/` возвращает 200 даже для FREE-пользователя без кабинетов, заказов и подписки.

На production наиболее вероятная причина 500 после локально зелёного flow — несовпадение схемы
БД и кода. Особое место риска: миграция `20260517_0013_subscription_lifecycle`, которая добавляет
`user_subscriptions.period`. Если она не применена, чтение подписок может падать SQL-ошибкой
в dashboard/subscription flow.

Чтобы production больше не был “слепым”, в `app/api/main.py` добавлено централизованное
логирование необработанных ошибок в middleware:

- `request_failed` пишет traceback и path/query в логи;
- `/web*` возвращает контролируемую HTML-страницу ошибки;
- чувствительные заголовки по-прежнему маскируются.

Это не заменяет исправление первопричины: traceback теперь нужно смотреть в логах `api`.

## Тесты

Добавлены regression-тесты:

- новый WB FBS-заказ готовит уведомление и не помечается отправленным заранее;
- существующий Ozon FBS-заказ с пустым `first_notified_at` попадает в retry-уведомление;
- уже уведомлённый FBS-заказ не создаёт дубль;
- WEB login flow продолжает рендерить dashboard без 500;
- необработанное исключение на WEB-like path возвращает контролируемую HTML-ошибку.

## Изменённые файлы

- `app/services/order_processing_service.py`
- `app/workers/tasks.py`
- `app/api/main.py`
- `tests/unit/test_fbs_order_notification_retries.py`
- `tests/integration/test_api_smoke.py`
- `PRODUCTION_DEBUG_CHECKLIST.md`
- `REFACTORING_AND_CRITICAL_FIXES_REPORT.md`
- `README.md`
- `DEPLOYMENT_CHECKLIST.md`

## Что выполнить на сервере

```bash
git pull
docker compose build api bot worker
docker compose up -d api bot worker
docker compose exec api alembic upgrade head
docker compose exec api python -c "import app.api.main; print('API OK')"
docker compose exec bot python -c "import app.bot.main; print('BOT OK')"
docker compose logs --tail=200 api
docker compose logs --tail=200 worker
```

После деплоя открыть WEB из Telegram и проверить worker-логи при новом FBS-заказе:

```bash
docker compose logs -f worker | grep -E "order_notification_prepared|unnotified_order_notification_retried|new_order_notification_sent|new_order_notification_send_failed"
```

## Риски и дальнейшие рекомендации

- Если production 500 останется, первым делом снять traceback из `request_failed` в логах `api`;
- проверить `alembic current` против `alembic heads`;
- убедиться, что контейнеры действительно пересобраны и запущены из актуального commit;
- при наличии старых FBS-заказов без `first_notified_at` новый polling должен попытаться отправить
  уведомления повторно, поэтому возможна одноразовая “догоняющая” отправка по ранее потерянным
  заказам.
