# Чеклист развертывания обновления 1.6.2

## Критические исправления
- ✅ Исправлена ошибка расчета налога (теперь от seller_payout, а не от gross_revenue)
- ✅ Добавлена система монетизации с подписками
- ✅ Интеграция с ЮКасса для приема платежей
- ✅ Добавлено админское управление тарифами через Telegram без создания ручных платежей
- ✅ Исправлено дублирование кода в subscription.py
- ✅ Включён централизованный HTML parse mode для Telegram-сообщений
- ✅ Добавлено безопасное HTML-экранирование динамических значений в ключевых сообщениях
- ✅ Web-кабинет приведён к Material-style design tokens и единой UI-оболочке
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
- Ошибки при обработке webhook от ЮКасса
- Ошибки расчета прибыли
