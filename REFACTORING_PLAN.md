# План рефакторинга и модернизации KUZ'KA.SELLER BOT

**Дата:** 2026-05-16  
**Версия:** 1.0  
**Статус:** Черновик для обсуждения

---

## 🔍 Анализ текущего состояния

### Сильные стороны проекта
✅ Хорошая архитектура с разделением слоев (repositories, services, handlers)  
✅ Async/await везде, современный Python 3.12  
✅ Использование SQLAlchemy 2.0 и Alembic для миграций  
✅ Нормализация данных от разных маркетплейсов  
✅ Web-кабинет с server-side rendering  
✅ Background workers на arq для фоновых задач  
✅ Система уведомлений с настройками  

### Критические проблемы

#### 🚨 1. НЕПРАВИЛЬНЫЙ РАСЧЕТ ПРИБЫЛИ
**Проблема:** Используется `discounted_price` как доход продавца, но это цена покупателя.

**Текущая логика (НЕВЕРНАЯ):**
```python
# app/services/marketplace_estimates.py:128
revenue = quantize_money((item.discounted_price or ZERO) * Decimal(item.quantity or 1))
profit = revenue - commission - logistics - other - cost - package - tax
```

**Что не так:**
- `discounted_price` — это цена, которую платит покупатель
- Доход продавца = `discounted_price` - комиссия МП - логистика - прочие расходы МП
- Сейчас комиссия вычитается из дохода продавца, но доход уже включает комиссию!

**Правильная формула:**
```
Цена покупателя (discounted_price) = 1000₽
Комиссия WB (15%) = 150₽
Логистика = 92₽
Прочие расходы МП = 10₽

Выручка продавца (к выплате от МП) = 1000 - 150 - 92 - 10 = 748₽
Себестоимость = 300₽
Упаковка = 20₽
Налог (6% УСН от выручки) = 748 * 0.06 = 44.88₽

Чистая прибыль = 748 - 300 - 20 - 44.88 = 383.12₽
```

**Текущий расчет (ОШИБКА):**
```
revenue = 1000₽  # discounted_price
profit = 1000 - 150 - 92 - 10 - 300 - 20 - 60 = 368₽  # налог от 1000, а не от 748!
```

#### 🚨 2. Отсутствие системы подписок и монетизации
- Нет моделей для тарифов и подписок
- Нет ограничений по функционалу
- Нет интеграции с платежными системами

#### 🚨 3. Отсутствие аналитики и метрик
- Нет отслеживания использования функций
- Нет метрик для принятия решений о развитии
- Нет A/B тестирования

---

## 📋 План исправлений и улучшений

### ЭТАП 1: Критические исправления (1-2 дня)

#### 1.1. Исправить расчет прибыли ⚠️ КРИТИЧНО

**Файлы для изменения:**
- `app/schemas/orders.py` — добавить поле `seller_payout` (выручка продавца)
- `app/services/marketplace_estimates.py` — исправить формулу
- `app/integrations/wb.py` — извлекать `ppvzForPay` (выплата продавцу)
- `app/integrations/ozon.py` — извлекать `payout` из финансовых данных

**Новая структура данных:**
```python
class NormalizedOrderItem:
    buyer_price: Decimal  # Цена покупателя (с учетом скидок)
    seller_payout: Decimal  # Выплата продавцу от МП (buyer_price - комиссия - логистика - прочее)
    marketplace_commission: Decimal  # Комиссия МП
    logistics_cost: Decimal  # Логистика
    other_marketplace_costs: Decimal  # Прочие расходы МП
```

**Новая формула прибыли:**
```python
def calculate_profit(item: OrderItem) -> Decimal:
    # Выручка продавца (уже за вычетом расходов МП)
    seller_revenue = item.seller_payout or (
        item.buyer_price 
        - item.marketplace_commission 
        - item.logistics_cost 
        - item.other_marketplace_costs
    )
    
    # Расходы продавца
    cost_price = item.cost_price_used or Decimal("0")
    package_cost = item.package_cost_used or Decimal("0")
    
    # Налог от выручки продавца, а не от цены покупателя!
    tax_base = seller_revenue
    tax_amount = tax_base * item.tax_rate
    
    # Чистая прибыль
    profit = seller_revenue - cost_price - package_cost - tax_amount
    
    return profit
```

#### 1.2. Добавить валидацию данных от МП

**Проблема:** Данные от WB/Ozon могут быть неполными или некорректными.

**Решение:**
- Добавить логирование всех извлеченных значений
- Добавить флаги достоверности данных
- Показывать пользователю, какие данные точные, а какие оценочные

---

### ЭТАП 2: Система подписок и монетизация (3-5 дней)

#### 2.1. Модели данных для подписок

**Новые таблицы:**

```python
# app/models/subscriptions.py

class SubscriptionTier(Base):
    """Тарифный план."""
    __tablename__ = "subscription_tiers"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)  # free, basic, pro, enterprise
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    price_monthly: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    price_yearly: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    
    # Лимиты
    max_marketplace_accounts: Mapped[int] = mapped_column(default=1)
    max_orders_per_month: Mapped[int | None]  # None = unlimited
    max_products: Mapped[int | None]
    
    # Доступ к функциям
    feature_web_cabinet: Mapped[bool] = mapped_column(default=True)
    feature_analytics: Mapped[bool] = mapped_column(default=False)
    feature_plan_fact: Mapped[bool] = mapped_column(default=False)
    feature_break_even: Mapped[bool] = mapped_column(default=False)
    feature_stock_forecast: Mapped[bool] = mapped_column(default=False)
    feature_alerts: Mapped[bool] = mapped_column(default=False)
    feature_api_access: Mapped[bool] = mapped_column(default=False)
    feature_priority_support: Mapped[bool] = mapped_column(default=False)
    
    is_active: Mapped[bool] = mapped_column(default=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now)


class UserSubscription(Base):
    """Подписка пользователя."""
    __tablename__ = "user_subscriptions"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tier_id: Mapped[int] = mapped_column(ForeignKey("subscription_tiers.id"))
    
    status: Mapped[str] = mapped_column(String(32))  # active, cancelled, expired, trial
    
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Для trial периода
    is_trial: Mapped[bool] = mapped_column(default=False)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Платежная информация
    payment_provider: Mapped[str | None] = mapped_column(String(32))  # yookassa, stripe
    payment_id: Mapped[str | None] = mapped_column(String(128))
    auto_renew: Mapped[bool] = mapped_column(default=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=datetime.now)
    
    # Relationships
    user: Mapped["User"] = relationship(back_populates="subscriptions")
    tier: Mapped["SubscriptionTier"] = relationship()


class Payment(Base):
    """История платежей."""
    __tablename__ = "payments"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    subscription_id: Mapped[int | None] = mapped_column(ForeignKey("user_subscriptions.id"))
    
    provider: Mapped[str] = mapped_column(String(32))  # yookassa
    provider_payment_id: Mapped[str] = mapped_column(String(128), unique=True)
    
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    
    status: Mapped[str] = mapped_column(String(32))  # pending, succeeded, cancelled
    
    payment_method: Mapped[str | None] = mapped_column(String(64))  # bank_card, yoo_money
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    metadata: Mapped[dict | None] = mapped_column(JSON)
    
    user: Mapped["User"] = relationship()
```

#### 2.2. Тарифные планы (предложение)

**FREE (Бесплатный)**
- 1 аккаунт маркетплейса
- До 100 заказов в месяц
- Базовые уведомления о заказах
- Расчет прибыли
- Цена: 0₽

**BASIC (Базовый)**
- 2 аккаунта маркетплейсов
- До 500 заказов в месяц
- Web-кабинет
- Аналитика заказов и прибыли
- Уведомления о выкупах
- Цена: 490₽/мес или 4900₽/год (экономия 2 месяца)

**PRO (Профессиональный)**
- 5 аккаунтов маркетплейсов
- Неограниченно заказов
- Все функции BASIC +
- План/факт анализ
- Безубыточная цена
- Прогноз остатков и out-of-stock
- Расширенные алерты
- Приоритетная поддержка
- Цена: 1490₽/мес или 14900₽/год

**ENTERPRISE (Корпоративный)**
- Неограниченно аккаунтов
- Все функции PRO +
- API доступ
- Кастомные интеграции
- Персональный менеджер
- Цена: по запросу

#### 2.3. Интеграция ЮКасса

**Файлы:**
- `app/integrations/yookassa.py` — клиент для ЮКасса API
- `app/services/payment_service.py` — сервис обработки платежей
- `app/services/subscription_service.py` — управление подписками
- `app/api/webhooks.py` — webhook для уведомлений от ЮКасса
- `app/bot/handlers/subscription.py` — хендлеры для управления подпиской

**Пример интеграции:**

```python
# app/integrations/yookassa.py
from yookassa import Configuration, Payment as YooPayment

class YooKassaClient:
    def __init__(self, shop_id: str, secret_key: str):
        Configuration.account_id = shop_id
        Configuration.secret_key = secret_key
    
    async def create_payment(
        self,
        amount: Decimal,
        description: str,
        return_url: str,
        metadata: dict | None = None,
    ) -> dict:
        """Создать платеж."""
        payment = YooPayment.create({
            "amount": {
                "value": str(amount),
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": return_url
            },
            "capture": True,
            "description": description,
            "metadata": metadata or {}
        })
        return payment
    
    async def get_payment(self, payment_id: str) -> dict:
        """Получить информацию о платеже."""
        return YooPayment.find_one(payment_id)
```

**Webhook обработка:**

```python
# app/api/webhooks.py
@router.post("/webhooks/yookassa")
async def yookassa_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Обработка уведомлений от ЮКасса."""
    payload = await request.json()
    
    # Проверка подписи
    # ...
    
    event_type = payload.get("event")
    payment_data = payload.get("object")
    
    if event_type == "payment.succeeded":
        await PaymentService(session).handle_payment_success(payment_data)
    elif event_type == "payment.canceled":
        await PaymentService(session).handle_payment_cancel(payment_data)
    
    return {"status": "ok"}
```

#### 2.4. Middleware для проверки подписки

```python
# app/bot/middlewares/subscription.py
class SubscriptionMiddleware(BaseMiddleware):
    """Проверка лимитов подписки."""
    
    async def __call__(
        self,
        handler: Callable,
        event: TelegramObject,
        data: dict,
    ):
        user = data.get("user")
        if not user:
            return await handler(event, data)
        
        subscription = await SubscriptionService(data["session"]).get_active(user.id)
        
        # Проверка лимитов
        if not subscription.can_add_account():
            await event.answer("Достигнут лимит аккаунтов. Обновите подписку.")
            return
        
        data["subscription"] = subscription
        return await handler(event, data)
```

---

### ЭТАП 3: Аналитика и метрики (2-3 дня)

#### 3.1. Система событий

```python
# app/services/analytics_service.py
class AnalyticsEvent(Base):
    """События для аналитики."""
    __tablename__ = "analytics_events"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    event_category: Mapped[str] = mapped_column(String(64))
    
    properties: Mapped[dict | None] = mapped_column(JSON)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=datetime.now,
        index=True
    )

# Примеры событий:
# - user_registered
# - order_notification_sent
# - web_cabinet_opened
# - subscription_purchased
# - feature_used (properties: {feature: "plan_fact"})
```

#### 3.2. Дашборд метрик (для админа)

- DAU/MAU (Daily/Monthly Active Users)
- Конверсия в платную подписку
- Churn rate (отток пользователей)
- ARPU (Average Revenue Per User)
- Популярность функций

---

### ЭТАП 4: Улучшение UX и функционала (5-7 дней)

#### 4.1. Онбординг новых пользователей

**Проблема:** Новый пользователь не понимает, что делать после /start

**Решение:**
- Интерактивный туториал с пошаговой настройкой
- Демо-данные для ознакомления
- Видео-инструкции

#### 4.2. Улучшенные уведомления

- Группировка уведомлений (дайджесты)
- Настройка времени уведомлений
- Умные уведомления (только важные события)

#### 4.3. Экспорт данных

- Экспорт в Excel/CSV
- Автоматические отчеты на email
- Интеграция с Google Sheets

#### 4.4. Мобильная оптимизация web-кабинета

- Адаптивный дизайн (уже есть, но можно улучшить)
- PWA (Progressive Web App)
- Офлайн режим

---

### ЭТАП 5: Масштабирование и производительность (3-5 дней)

#### 5.1. Кэширование

```python
# app/core/cache.py
import redis.asyncio as redis

class CacheService:
    def __init__(self):
        self.redis = redis.from_url(settings.redis_url)
    
    async def get_user_subscription(self, user_id: int) -> dict | None:
        """Кэш подписки пользователя."""
        key = f"subscription:{user_id}"
        data = await self.redis.get(key)
        return json.loads(data) if data else None
    
    async def set_user_subscription(self, user_id: int, data: dict, ttl: int = 3600):
        await self.redis.setex(
            f"subscription:{user_id}",
            ttl,
            json.dumps(data)
        )
```

#### 5.2. Оптимизация запросов к БД

- Добавить индексы на часто используемые поля
- Использовать `selectinload` для связанных данных
- Пагинация для больших списков

#### 5.3. Rate limiting

```python
# app/bot/middlewares/rate_limit.py
class RateLimitMiddleware(BaseMiddleware):
    """Защита от спама."""
    
    async def __call__(self, handler, event, data):
        user_id = event.from_user.id
        key = f"rate_limit:{user_id}"
        
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 60)
        
        if count > 30:  # 30 запросов в минуту
            await event.answer("Слишком много запросов. Подождите минуту.")
            return
        
        return await handler(event, data)
```

---

### ЭТАП 6: Дополнительные функции (опционально)

#### 6.1. Telegram Mini App

- Встроенное веб-приложение в Telegram
- Нативный UX без выхода из мессенджера

#### 6.2. Интеграция с 1С

- Выгрузка заказов в 1С
- Синхронизация себестоимости

#### 6.3. Маркетплейс интеграций

- Подключение сторонних сервисов
- API для разработчиков

#### 6.4. AI-ассистент

- Рекомендации по ценообразованию
- Прогнозирование продаж
- Автоматическое выявление проблем

---

## 🎯 Приоритеты

### Критично (сделать в первую очередь):
1. ✅ Исправить расчет прибыли
2. ✅ Добавить систему подписок
3. ✅ Интегрировать ЮКасса

### Важно (следующий спринт):
4. Добавить аналитику использования
5. Улучшить онбординг
6. Оптимизировать производительность

### Желательно (backlog):
7. Экспорт данных
8. Telegram Mini App
9. AI-ассистент

---

## 📊 Оценка трудозатрат

| Этап | Задача | Время | Приоритет |
|------|--------|-------|-----------|
| 1 | Исправление расчета прибыли | 1-2 дня | 🔴 Критично |
| 2 | Система подписок (модели + миграции) | 1 день | 🔴 Критично |
| 2 | Интеграция ЮКасса | 2 дня | 🔴 Критично |
| 2 | UI для управления подпиской | 1 день | 🔴 Критично |
| 3 | Система аналитики | 2-3 дня | 🟡 Важно |
| 4 | Улучшение UX | 5-7 дней | 🟡 Важно |
| 5 | Оптимизация | 3-5 дней | 🟢 Желательно |

**Итого для MVP монетизации:** ~7-10 дней

---

## 🚀 Roadmap

### Неделя 1-2: Критические исправления
- Исправить расчет прибыли
- Добавить модели подписок
- Интегрировать ЮКасса
- Базовый UI для подписки

### Неделя 3-4: Аналитика и улучшения
- Система событий и метрик
- Улучшенный онбординг
- Экспорт данных

### Неделя 5-6: Оптимизация
- Кэширование
- Rate limiting
- Мониторинг производительности

### Неделя 7+: Дополнительные функции
- Telegram Mini App
- Расширенная аналитика
- AI-функции

---

## 💡 Рекомендации

1. **Начать с исправления расчетов** — это критично для доверия пользователей
2. **Запустить trial период** — 14 дней бесплатно для всех новых пользователей
3. **A/B тестирование цен** — протестировать разные ценовые модели
4. **Собирать feedback** — добавить форму обратной связи в бот
5. **Мониторинг ошибок** — интегрировать Sentry для отслеживания багов
6. **Документация API** — если планируется открытый API

---

## 📝 Следующие шаги

1. Обсудить и утвердить план
2. Создать задачи в трекере (GitHub Issues / Jira)
3. Начать с исправления расчета прибыли
4. Параллельно проектировать систему подписок
5. Настроить тестовый аккаунт ЮКасса

---

**Вопросы для обсуждения:**
- Согласны ли с предложенными тарифами?
- Какие функции должны быть в FREE, а какие платными?
- Нужен ли trial период?
- Какие еще маркетплейсы планируется добавить?
