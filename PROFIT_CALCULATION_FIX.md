# Исправление расчета прибыли

## Проблема

Текущий расчет использует `discounted_price` (цену покупателя) как базу для расчета прибыли, но это неверно.

### Текущая (НЕПРАВИЛЬНАЯ) логика:

```python
# app/services/marketplace_estimates.py:128
revenue = item.discounted_price * quantity  # Цена покупателя
profit = revenue - commission - logistics - other - cost - package - tax
```

**Что не так:**
- `discounted_price` — это цена, которую платит покупатель
- Комиссия и логистика уже вычтены маркетплейсом из этой суммы
- Продавец получает `discounted_price - commission - logistics - other`
- Налог должен считаться от выручки продавца, а не от цены покупателя

### Правильная логика:

```
Цена покупателя (buyer_price) = 1000₽
Комиссия МП (15%) = 150₽
Логистика = 92₽
Прочие расходы МП = 10₽

Выручка продавца (seller_payout) = 1000 - 150 - 92 - 10 = 748₽

Себестоимость = 300₽
Упаковка = 20₽
Налог (6% УСН от выручки продавца) = 748 * 0.06 = 44.88₽

Чистая прибыль = 748 - 300 - 20 - 44.88 = 383.12₽
Маржа = 383.12 / 748 * 100 = 51.2%
```

## Решение

### 1. Обновить схемы данных

**app/schemas/orders.py:**

```python
class NormalizedOrderItem(BaseModel):
    # Цены
    buyer_price: Decimal = Decimal("0")  # Цена покупателя (с учетом скидок)
    seller_price: Decimal = Decimal("0")  # Цена продавца (без скидок МП)
    discounted_price: Decimal = Decimal("0")  # = buyer_price (для обратной совместимости)
    
    # Выплата продавцу (buyer_price - все расходы МП)
    payout_amount_estimated: Decimal | None = None  # Выплата от МП
    
    # Расходы маркетплейса (вычитаются из buyer_price)
    commission_estimated: Decimal | None = None
    logistics_estimated: Decimal | None = None
    other_marketplace_expenses_estimated: Decimal | None = None
```

### 2. Обновить извлечение данных из WB API

**app/integrations/wb.py:**

```python
def normalize_fbs_order(self, payload: dict[str, Any]) -> NormalizedOrder:
    # Цена покупателя (в копейках, конвертируем в рубли)
    buyer_price = self.extract_fbs_order_price(payload)
    
    # Извлекаем расходы МП
    commission = self._extract_commission(payload, buyer_price)
    logistics = self._extract_logistics(payload)
    other = self._extract_other_expenses(payload)
    
    # Выплата продавцу = цена покупателя - все расходы МП
    payout = buyer_price - (commission or Decimal("0")) - logistics - other
    
    item = NormalizedOrderItem(
        buyer_price=buyer_price,
        seller_price=buyer_price,  # Для FBS обычно совпадает
        discounted_price=buyer_price,  # Обратная совместимость
        payout_amount_estimated=payout,  # ← КЛЮЧЕВОЕ ИЗМЕНЕНИЕ
        commission_estimated=commission,
        logistics_estimated=logistics,
        other_marketplace_expenses_estimated=other,
        ...
    )
```

**Для финансовых отчетов WB:**

```python
def normalize_report_order(self, payload: dict[str, Any]) -> NormalizedOrder:
    # В финансовых отчетах WB есть поле ppvzForPay - это выплата продавцу
    buyer_price = Decimal(str(payload.get("retailPriceWithDiscRub") or 0))
    payout = Decimal(str(payload.get("ppvzForPay") or 0))  # ← Используем готовое значение
    
    commission = self._extract_commission(payload, buyer_price)
    logistics = self._extract_logistics(payload)
    other = self._extract_other_expenses(payload)
    
    item = NormalizedOrderItem(
        buyer_price=buyer_price,
        discounted_price=buyer_price,
        payout_amount_estimated=payout,  # ← Точное значение от WB
        commission_estimated=commission,
        logistics_estimated=logistics,
        other_marketplace_expenses_estimated=other,
        ...
    )
```

### 3. Исправить расчет прибыли

**app/services/marketplace_estimates.py:**

```python
def calculate_planned_economics(
    order: Order,
    item: OrderItem,
    *,
    product_commission_rate: Decimal | None = None,
) -> PlannedEconomics:
    """Calculate display-safe planned profit with baseline estimates when needed."""
    
    expenses = estimate_marketplace_expenses(
        order, item, product_commission_rate=product_commission_rate
    )
    
    # Цена покупателя
    buyer_price = quantize_money((item.discounted_price or ZERO) * Decimal(item.quantity or 1))
    
    # Выручка продавца (после вычета расходов МП)
    seller_payout = quantize_money(item.payout_amount_estimated or ZERO)
    if seller_payout == ZERO:
        # Если нет точного значения, рассчитываем
        seller_payout = buyer_price - expenses.commission - expenses.logistics
    
    # Расходы продавца
    cost = quantize_money(item.cost_price_used or ZERO)
    package = quantize_money(item.package_cost_used or ZERO)
    
    # Налог от выручки продавца, а не от цены покупателя!
    tax_base = seller_payout
    tax = quantize_money(item.tax_amount_estimated or ZERO)
    if tax == ZERO and item.tax_rate:
        tax = quantize_money(tax_base * item.tax_rate)
    
    # Чистая прибыль
    profit = quantize_money(seller_payout - cost - package - tax)
    
    # Маржа от выручки продавца
    margin = quantize_money(profit / seller_payout * Decimal("100")) if seller_payout > ZERO else ZERO
    
    return PlannedEconomics(
        revenue=buyer_price,  # Для отображения пользователю
        seller_payout=seller_payout,  # ← НОВОЕ ПОЛЕ
        commission=expenses.commission,
        commission_rate=expenses.commission_rate,
        commission_is_known=expenses.commission_is_known,
        commission_is_baseline=expenses.commission_is_baseline,
        commission_source=expenses.commission_source,
        logistics=expenses.logistics,
        logistics_is_known=expenses.logistics_is_known,
        logistics_is_baseline=expenses.logistics_is_baseline,
        logistics_source=expenses.logistics_source,
        other_marketplace_costs=quantize_money(item.other_marketplace_expenses_estimated or ZERO),
        cost_price=cost,
        package_cost=package,
        tax_amount=tax,
        profit=profit,
        margin_percent=margin,
        confidence=expenses.confidence,
    )
```

**app/services/profit_calculator.py:**

```python
class ProfitCalculator:
    """Calculate marketplace order economics from separated expense types."""
    
    def calculate(self, data: ProfitInput) -> ProfitResult:
        cost = data.cost or CostInput()
        missing_cost = data.cost is None or cost.cost_price == 0
        warnings: list[str] = []
        
        if missing_cost:
            warnings.append("Себестоимость не задана. Прибыль рассчитана без учёта себестоимости")
        
        # Расходы маркетплейса
        marketplace_commission = data.marketplace_commission or Decimal("0")
        marketplace_expenses = (
            marketplace_commission
            + data.logistics_cost
            + data.acquiring_cost
            + data.storage_cost
            + data.return_cost
            + data.other_marketplace_costs
        )
        
        # Выручка продавца (после вычета расходов МП)
        seller_payout = data.expected_payout
        if seller_payout is None:
            seller_payout = data.gross_revenue - marketplace_expenses
        
        # Налоговая база = выручка продавца, а не цена покупателя!
        tax_base = seller_payout
        tax_amount = money(tax_base * cost.tax_rate)
        
        # Расходы продавца
        seller_expenses = cost.cost_price + cost.package_cost + cost.additional_cost + tax_amount
        
        # Чистая прибыль
        profit = money(seller_payout - seller_expenses)
        
        # Маржа от выручки продавца
        margin = Decimal("0")
        if seller_payout > 0:
            margin = (profit / seller_payout * Decimal("100")).quantize(
                PERCENT_QUANT,
                rounding=ROUND_HALF_UP,
            )
        
        return ProfitResult(
            gross_revenue=money(data.gross_revenue),  # Цена покупателя
            expected_payout=money(seller_payout),  # Выручка продавца
            marketplace_commission=money(marketplace_commission),
            logistics_cost=money(data.logistics_cost),
            acquiring_cost=money(data.acquiring_cost),
            storage_cost=money(data.storage_cost),
            return_cost=money(data.return_cost),
            other_marketplace_costs=money(data.other_marketplace_costs),
            cost_price=money(cost.cost_price),
            package_cost=money(cost.package_cost),
            additional_seller_cost=money(cost.additional_cost),
            tax_amount=tax_amount,
            profit=profit,
            margin_percent=margin,
            missing_cost=missing_cost,
            warnings=warnings,
        )
```

### 4. Обновить модели БД

**Миграция:**

```python
"""add seller payout field

Revision ID: xxxx
"""

def upgrade() -> None:
    op.add_column('order_items', sa.Column('seller_payout_estimated', sa.Numeric(12, 2), nullable=True))
    op.add_column('order_items', sa.Column('tax_rate', sa.Numeric(5, 4), nullable=True))
    
    # Пересчитать для существующих записей
    op.execute("""
        UPDATE order_items 
        SET seller_payout_estimated = payout_amount_estimated
        WHERE payout_amount_estimated IS NOT NULL
    """)

def downgrade() -> None:
    op.drop_column('order_items', 'seller_payout_estimated')
    op.drop_column('order_items', 'tax_rate')
```

### 5. Обновить отображение в уведомлениях

**app/services/order_card_service.py:**

```python
def _format_wb_fbs_order(...) -> str:
    economics = calculate_planned_economics(...)
    
    lines = [
        format_datetime_for_user(order.order_date, timezone_name),
        "",
        f"🛒 #Заказ: {rub(economics.revenue)}",  # Цена покупателя
        f"💰 К выплате: {rub(economics.seller_payout)}",  # ← НОВОЕ: выручка продавца
        ...,
        "",
        "📊 Плановый результат:",
        f"Выручка продавца: {rub(economics.seller_payout)}",  # ← Показываем явно
        f"Прибыль: {rub(economics.profit)}",
        f"Маржа: {economics.margin_percent}%",
        confidence_label(economics.confidence),
    ]
```

## Тестирование

### Тест-кейс 1: WB FBS заказ

**Входные данные:**
```python
buyer_price = 1000₽
commission = 150₽ (15%)
logistics = 92₽
other = 10₽
cost_price = 300₽
package = 20₽
tax_rate = 0.06 (6% УСН)
```

**Ожидаемый результат:**
```python
seller_payout = 1000 - 150 - 92 - 10 = 748₽
tax = 748 * 0.06 = 44.88₽
profit = 748 - 300 - 20 - 44.88 = 383.12₽
margin = 383.12 / 748 * 100 = 51.2%
```

### Тест-кейс 2: Ozon FBO заказ

**Входные данные:**
```python
buyer_price = 2000₽
commission = 340₽ (17%)
logistics = 150₽
other = 25₽
cost_price = 800₽
package = 30₽
tax_rate = 0.06
```

**Ожидаемый результат:**
```python
seller_payout = 2000 - 340 - 150 - 25 = 1485₽
tax = 1485 * 0.06 = 89.10₽
profit = 1485 - 800 - 30 - 89.10 = 565.90₽
margin = 565.90 / 1485 * 100 = 38.1%
```

## Миграция данных

После внедрения исправлений нужно пересчитать прибыль для всех существующих заказов:

```python
# scripts/recalculate_profits.py
async def recalculate_all_profits():
    async with AsyncSessionFactory() as session:
        orders = await session.execute(
            select(Order).options(selectinload(Order.items))
        )
        
        for order in orders.scalars():
            for item in order.items:
                # Пересчитать с новой формулой
                economics = calculate_planned_economics(order, item)
                item.profit_estimated = economics.profit
                item.margin_percent_estimated = economics.margin_percent
        
        await session.commit()
```

## Чеклист внедрения

- [ ] Обновить схемы Pydantic
- [ ] Обновить интеграции WB/Ozon
- [ ] Исправить расчет в marketplace_estimates.py
- [ ] Исправить ProfitCalculator
- [ ] Создать миграцию БД
- [ ] Обновить отображение в уведомлениях
- [ ] Написать unit-тесты
- [ ] Пересчитать существующие данные
- [ ] Протестировать на реальных заказах
- [ ] Задеплоить на прод

## Риски

1. **Изменение исторических данных** — старые расчеты будут отличаться от новых
   - Решение: добавить поле `calculation_version` для отслеживания

2. **Пользователи привыкли к старым цифрам** — может быть confusion
   - Решение: показать уведомление об улучшении расчетов

3. **Отсутствие данных о выплате** — для старых заказов может не быть `payout_amount`
   - Решение: рассчитывать на основе имеющихся данных
