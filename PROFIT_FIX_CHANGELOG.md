# Исправление расчета прибыли — Changelog

**Дата:** 2026-05-16  
**Версия:** 1.5.0  
**Статус:** ✅ Реализовано и протестировано

---

## 🎯 Проблема

Бот **неправильно рассчитывал прибыль**, используя цену покупателя (`discounted_price`) как базу для расчета, вместо выручки продавца после вычета расходов маркетплейса.

### Старая (НЕПРАВИЛЬНАЯ) формула:

```python
revenue = discounted_price  # Цена покупателя
profit = revenue - commission - logistics - other - cost - package - tax
tax = revenue * tax_rate  # Налог от цены покупателя!
```

**Что было не так:**
- Комиссия и логистика вычитались из цены покупателя, но они уже удержаны маркетплейсом
- Налог считался от цены покупателя, а не от выручки продавца
- Маржа считалась от неправильной базы

### Новая (ПРАВИЛЬНАЯ) формула:

```python
seller_payout = discounted_price - commission - logistics - other  # Выручка продавца
tax = seller_payout * tax_rate  # Налог от выручки продавца!
profit = seller_payout - cost - package - tax
margin = profit / seller_payout * 100
```

---

## ✅ Реализованные изменения

### 1. Обновлены схемы данных

**`app/schemas/orders.py`:**
- Добавлено поле `seller_payout_estimated: Decimal | None` — выручка продавца после вычета расходов МП

### 2. Обновлены модели БД

**`app/models/domain.py`:**
- Добавлено поле `seller_payout_estimated` в `OrderItem`
- Добавлено поле `tax_rate` в `OrderItem` для хранения ставки налога

**Миграция:** `migrations/versions/20260516_0010_seller_payout_and_tax_rate.py`
- Создает новые поля
- Автоматически заполняет `seller_payout_estimated` из `payout_amount_estimated` для существующих записей

### 3. Исправлен расчет прибыли

**`app/services/profit_calculator.py`:**
```python
# Выручка продавца (после вычета расходов МП)
seller_payout = data.expected_payout
if seller_payout is None:
    seller_payout = data.gross_revenue - marketplace_expenses

# Налоговая база = выручка продавца, а не цена покупателя!
tax_base = data.tax_base if data.tax_base is not None else seller_payout
tax_amount = money(tax_base * cost.tax_rate)

# Чистая прибыль
profit = money(seller_payout - seller_expenses)

# Маржа от выручки продавца
margin = (profit / seller_payout * Decimal("100")) if seller_payout > 0 else Decimal("0")
```

**`app/services/marketplace_estimates.py`:**
```python
# Выручка продавца (seller payout) = цена покупателя - расходы МП
seller_payout = quantize_money(item.payout_amount_estimated or ZERO)
if seller_payout == ZERO:
    seller_payout = quantize_money(
        buyer_price - expenses.commission - expenses.logistics - other
    )

# Налог от выручки продавца, а не от цены покупателя!
tax_base = seller_payout
tax = quantize_money(item.tax_amount_estimated or ZERO)
if tax == ZERO and item.tax_rate:
    tax = quantize_money(tax_base * item.tax_rate)

# Чистая прибыль
profit = quantize_money(seller_payout - cost - package - tax)

# Маржа от выручки продавца
margin = (
    quantize_money(profit / seller_payout * Decimal("100"))
    if seller_payout > ZERO
    else ZERO
)
```

### 4. Обновлены интеграции с маркетплейсами

**`app/integrations/wb.py`:**
- `normalize_fbs_order()` — рассчитывает `seller_payout_estimated`
- `normalize_report_order()` — использует `ppvzForPay` от WB как точное значение выплаты
- `normalize_statistics_order()` — рассчитывает выручку продавца

**`app/integrations/ozon.py`:**
- `_normalize_products()` — использует `payout` из финансовых данных или рассчитывает вручную

### 5. Обновлены уведомления

**`app/services/order_card_service.py`:**
- Добавлена строка "💰 К выплате: {seller_payout}" в уведомления о заказах
- Обновлен раздел "📊 Плановый результат" с отображением выручки продавца

**Пример нового уведомления:**
```
🛒 #Заказ: 1000₽
💰 К выплате: 748₽
📈 Сегодня: 5 на 5000₽

📊 Плановый результат:
Выручка продавца: 748₽
Прибыль: 383.12₽
Маржа: 51.2%
✅ Расчёт точный
```

### 6. Обновлены тесты

**`tests/unit/test_profit_calculator.py`:**
- Обновлены ожидаемые значения под новую формулу
- Все 6 тестов проходят успешно ✅

---

## 📊 Примеры расчетов

### Пример 1: WB FBS заказ

**Входные данные:**
```
Цена покупателя: 1000₽
Комиссия WB (15%): 150₽
Логистика: 92₽
Прочие расходы МП: 10₽
Себестоимость: 300₽
Упаковка: 20₽
Налог (УСН 6%): ?
```

**Старый (НЕПРАВИЛЬНЫЙ) расчет:**
```
revenue = 1000₽
tax = 1000 * 0.06 = 60₽
profit = 1000 - 150 - 92 - 10 - 300 - 20 - 60 = 368₽
margin = 368 / 1000 * 100 = 36.8%
```

**Новый (ПРАВИЛЬНЫЙ) расчет:**
```
seller_payout = 1000 - 150 - 92 - 10 = 748₽
tax = 748 * 0.06 = 44.88₽
profit = 748 - 300 - 20 - 44.88 = 383.12₽
margin = 383.12 / 748 * 100 = 51.2%
```

**Разница:** +15.12₽ прибыли, +14.4% маржи

### Пример 2: Ozon FBO заказ

**Входные данные:**
```
Цена покупателя: 2000₽
Комиссия Ozon (17%): 340₽
Логистика: 150₽
Прочие расходы МП: 25₽
Себестоимость: 800₽
Упаковка: 30₽
Налог (УСН 6%): ?
```

**Старый (НЕПРАВИЛЬНЫЙ) расчет:**
```
revenue = 2000₽
tax = 2000 * 0.06 = 120₽
profit = 2000 - 340 - 150 - 25 - 800 - 30 - 120 = 535₽
margin = 535 / 2000 * 100 = 26.75%
```

**Новый (ПРАВИЛЬНЫЙ) расчет:**
```
seller_payout = 2000 - 340 - 150 - 25 = 1485₽
tax = 1485 * 0.06 = 89.10₽
profit = 1485 - 800 - 30 - 89.10 = 565.90₽
margin = 565.90 / 1485 * 100 = 38.1%
```

**Разница:** +30.90₽ прибыли, +11.35% маржи

---

## 🚀 Как применить изменения

### 1. Применить миграцию БД

```bash
# Локально
alembic upgrade head

# В Docker
docker compose run --rm api alembic upgrade head
```

### 2. Перезапустить сервисы

```bash
# Локально
make bot
make worker

# В Docker
docker compose restart bot worker
```

### 3. (Опционально) Пересчитать существующие данные

Для пересчета прибыли по всем существующим заказам можно создать скрипт:

```python
# scripts/recalculate_profits.py
async def recalculate_all_profits():
    async with AsyncSessionFactory() as session:
        orders = await session.execute(
            select(Order).options(selectinload(Order.items))
        )
        
        for order in orders.scalars():
            for item in order.items:
                economics = calculate_planned_economics(order, item)
                item.profit_estimated = economics.profit
                item.margin_percent_estimated = economics.margin_percent
                item.seller_payout_estimated = economics.seller_payout
        
        await session.commit()
```

---

## ⚠️ Важные замечания

1. **Исторические данные:** Старые расчеты будут отличаться от новых. Это нормально — старые были неправильными.

2. **Уведомления пользователям:** Рекомендуется отправить уведомление об улучшении точности расчетов.

3. **Отсутствие данных о выплате:** Для старых заказов может не быть точного значения `payout_amount`. В этом случае система рассчитывает его на основе имеющихся данных.

4. **Налоговая база:** Теперь налог правильно считается от выручки продавца, а не от цены покупателя.

---

## ✅ Проверка

- [x] Обновлены схемы Pydantic
- [x] Обновлены модели SQLAlchemy
- [x] Создана миграция БД
- [x] Исправлен ProfitCalculator
- [x] Исправлен marketplace_estimates
- [x] Обновлены интеграции WB
- [x] Обновлены интеграции Ozon
- [x] Обновлены уведомления
- [x] Обновлены unit-тесты
- [x] Все тесты проходят (6/6) ✅
- [x] Линтер проходит без ошибок ✅

---

## 📝 Следующие шаги

1. **Протестировать на реальных данных** — проверить расчеты на реальных заказах от WB и Ozon
2. **Задеплоить на прод** — применить миграцию и перезапустить сервисы
3. **Мониторинг** — следить за корректностью расчетов в первые дни после деплоя
4. **Уведомить пользователей** — отправить сообщение об улучшении точности расчетов

---

**Автор:** Claude Code  
**Дата:** 2026-05-16
