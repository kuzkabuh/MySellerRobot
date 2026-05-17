# Чеклист развертывания обновления 1.6.3

## Критические исправления
- ✅ Исправлена ошибка расчета налога (теперь от seller_payout, а не от gross_revenue)
- ✅ Добавлена система монетизации с подписками
- ✅ Интеграция с ЮКасса для приема платежей
- ✅ Добавлено админское управление тарифами через Telegram без создания ручных платежей
- ✅ Исправлено дублирование кода в subscription.py
- ✅ Включён централизованный HTML parse mode для Telegram-сообщений
- ✅ Добавлено безопасное HTML-экранирование динамических значений в ключевых сообщениях
- ✅ Web-кабинет приведён к Material-style design tokens и единой UI-оболочке
- ✅ Добавлен жизненный цикл подписки: monthly/yearly, trial, expiration и upgrade BASIC → PRO
- ✅ FBS-уведомления стали retryable: заказ отмечается уведомлённым только после успешной
  отправки Telegram-сообщения
- ✅ WEB 500 теперь логируется событием `request_failed` с traceback и возвращает контролируемую
  HTML-страницу вместо слепого Internal Server Error
- ✅ Добавлена зависимость yookassa в pyproject.toml

## Шаги развертывания

### 1. Установка зависимостей
```bash
pip install -e ".[dev]"
# или
pip install yookassa
```

### 2. Применение миграций
```bash
alembic upgrade head
```

Будут применены миграции:
- `20260516_0010` — добавление seller_payout_estimated и tax_rate
- `20260516_0011` — создание таблиц подписок и платежей
- `20260516_0012` — выравнивание каталога тарифов и включение ENTERPRISE
- `20260517_0013` — поле `period` в `user_subscriptions` и статус `REPLACED` для upgrade
- `20260517_0014` — production-safe проверка колонки `payments.payment_metadata`

### 3. Настройка переменных окружения

Добавьте в `.env`:
```env
# ЮКасса
YOOKASSA_SHOP_ID=your_shop_id
YOOKASSA_SECRET_KEY=your_secret_key

# Базовый URL для веб-кабинета (для return_url после оплаты)
WEB_BASE_URL=https://your-domain.com

# Контакт поддержки для экранов подписок и ENTERPRISE
SUPPORT_TELEGRAM_USERNAME=mpcontrol_support
```

### 4. Регистрация webhook в ЮКасса

После развертывания зарегистрируйте webhook URL в личном кабинете ЮКасса:
```
https://your-domain.com/webhooks/yookassa
```

События для подписки:
- `payment.succeeded`
- `payment.canceled`

### 5. Проверка работоспособности

```bash
# Проверка импорта
python -c "import app.bot.main; print('BOT OK')"
python -c "import app.api.main; print('API OK')"

# Проверка роутеров
python -c "from app.bot.main import create_dispatcher; dp = create_dispatcher(); print('Routers:', [r.name for r in dp.sub_routers])"

# Проверка версии API
python -c "from app.api.main import create_app; app = create_app(); print(app.version)"

# Запуск бота
python -m app.bot.main
```

### 6. Тестирование функционала

1. Отправьте `/start` боту — должен ответить
2. Отправьте `/subscription` — должен показать текущий тариф (FREE)
3. Попробуйте выбрать платный тариф — должна создаться ссылка на оплату
4. После тестовой оплаты проверьте активацию подписки
5. Для админа из `ADMIN_TELEGRAM_IDS` откройте `🛠 Администрирование` →
   `💳 Управление тарифами` и проверьте ручное назначение тарифа тестовому пользователю.
6. Проверьте, что в Telegram не видны сырые теги `<b>`/`<i>`/`<code>` и пользовательские значения
   с символами `<`/`>` отображаются как текст.
7. Откройте web-кабинет и проверьте страницы `/web/`, `/web/orders`, `/web/profit`,
   `/web/settings` на desktop и узком экране.
8. Проверьте новые рабочие WEB-разделы без заглушек:
   `/web/sales`, `/web/returns`, `/web/analytics`, `/web/control`, `/web/costs`,
   `/web/profile`, `/web/subscription`, `/web/accounts`.
9. На `/web/costs` откройте товар, добавьте новую себестоимость и убедитесь, что запись
   появляется в истории себестоимости.
10. Обязательно проверьте полный WEB login flow из Telegram: нажмите кнопку WEB-кабинета,
    убедитесь, что `/web/login?token=...` выставляет cookie, редиректит на `/web/`, а главная
    страница открывается с кодом 200 даже у FREE-пользователя без кабинетов, заказов и подписки.
11. Проверьте, что миграции/seed создали тариф `free` в `subscription_tiers`. WEB имеет
    защитный fallback, но рабочая БД должна содержать полный каталог тарифов.
12. Проверьте подписочный lifecycle:
    - monthly создаёт 30 дней;
    - yearly создаёт 365 дней;
    - повторная оплата текущего тарифа продлевает срок от действующего `expires_at`;
    - BASIC → PRO переводит старую подписку в `REPLACED`;
    - истёкшие trial/paid подписки не считаются активными.
13. Проверьте FBS-уведомления в worker-логах. Для нового FBS-заказа ожидается цепочка
    `order_persisted` → `order_notification_prepared` → `new_order_notification_sent`.
    Если отправка падает, следующий polling должен показать
    `unnotified_order_notification_retried`.
14. Если WEB на production всё ещё отдаёт 500, используйте `PRODUCTION_DEBUG_CHECKLIST.md`:
    проверьте `alembic current`, наличие миграции `20260517_0013_subscription_lifecycle` и
    событие `request_failed` в логах `api`.
15. Проверьте Telegram FSM: начните ручной ввод себестоимости, затем отправьте `/start` и `/menu`.
    Обе команды должны сбросить сценарий и открыть главное меню без сообщения о неверном формате.

## Откат в случае проблем

```bash
# Откат миграций
alembic downgrade 20260516_0010

# Перезапуск старой версии
git checkout <previous_commit>
systemctl restart seller-bot
```

## Известные проблемы и решения

### Проблема: ModuleNotFoundError: No module named 'yookassa'
**Решение**: `pip install yookassa`

### Проблема: Бот не отвечает на команды
**Решение**: Проверьте, что subscription_router зарегистрирован в app/bot/main.py

### Проблема: SQLAlchemy InvalidRequestError с 'metadata'
**Решение**: Уже исправлено — используется payment_metadata вместо metadata

## Мониторинг после развертывания

Проверьте логи на наличие ошибок:
```bash
docker compose logs bot --tail=100 -f
docker compose logs api --tail=100 -f
```

Обратите внимание на:
- Ошибки импорта модулей
- Ошибки подключения к БД
- `free_tier_missing_using_safe_fallback` после деплоя: такой warning означает, что WEB защищён
  от падения, но каталог тарифов в БД нужно досеять миграциями/seed-скриптом
- Ошибки при обработке webhook от ЮКасса
- Ошибки расчета прибыли
- `new_order_notification_send_failed` в worker-логах: заказ не будет помечен отправленным и
  должен повториться при следующем polling
- `request_failed` в api-логах: это точка входа для диагностики production WEB 500
