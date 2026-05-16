"""version: 1.2.0
description: Unit tests for Telegram order action cards, tariffs, and timezone formatting.
updated: 2026-05-15
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.bot.handlers.common import _format_order_details
from app.models.domain import Order, OrderItem, Product
from app.models.enums import Marketplace, SaleModel


class FakeSession:
    def __init__(self, product: Product | None = None) -> None:
        self.product = product

    async def get(self, model, row_id):  # type: ignore[no-untyped-def]
        return self.product


@pytest.mark.asyncio
async def test_order_details_card_contains_financial_breakdown_and_user_timezone() -> None:
    order = Order(
        id=10,
        user_id=1,
        marketplace_account_id=1,
        marketplace=Marketplace.WB,
        order_external_id="13833713",
        order_date=datetime(2026, 5, 15, 8, 33, tzinfo=UTC),
        event_received_at=datetime(2026, 5, 15, 8, 34, tzinfo=UTC),
        sale_model=SaleModel.FBS,
        status="new",
        normalized_status="new",
        warehouse="1745949",
    )
    order.items = [
        OrderItem(
            id=20,
            order_id=10,
            title="Товар WB",
            seller_article="W4079",
            marketplace_article="303948126",
            quantity=1,
            discounted_price=Decimal("411"),
            payout_amount_estimated=Decimal("411"),
            commission_estimated=Decimal("41"),
            logistics_estimated=Decimal("0"),
            cost_price_used=Decimal("100"),
            tax_amount_estimated=Decimal("25"),
            profit_estimated=Decimal("245"),
            margin_percent_estimated=Decimal("59.61"),
        )
    ]

    text = await _format_order_details(FakeSession(), order, "Europe/Moscow")

    assert "📦 Детали заказа" in text
    assert "Артикул продавца: W4079" in text
    assert "Цена продажи: 411 ₽" in text
    assert "Комиссия маркетплейса: 41 ₽" in text
    assert "Логистика: 92 ₽ (базовая)" in text
    assert "Прибыль: 153 ₽" in text
    assert "15.05.2026 11:33" in text


@pytest.mark.asyncio
async def test_order_details_uses_wb_tariff_commission_and_baseline_logistics() -> None:
    order = Order(
        id=11,
        user_id=1,
        marketplace_account_id=1,
        marketplace=Marketplace.WB,
        order_external_id="5052941915",
        order_date=datetime(2026, 5, 15, 14, 16, tzinfo=UTC),
        event_received_at=datetime(2026, 5, 15, 14, 17, tzinfo=UTC),
        sale_model=SaleModel.FBS,
        status="new",
        normalized_status="new",
        warehouse="1745949",
    )
    order.items = [
        OrderItem(
            id=21,
            order_id=11,
            product_id=30,
            title="Губка спонж для умывания черный лицо",
            seller_article="W4040",
            marketplace_article="304534278",
            quantity=1,
            discounted_price=Decimal("417"),
            payout_amount_estimated=Decimal("417"),
            commission_estimated=None,
            logistics_estimated=Decimal("0"),
            cost_price_used=Decimal("183"),
            tax_amount_estimated=Decimal("29"),
            profit_estimated=Decimal("154"),
            margin_percent_estimated=Decimal("37.02"),
        )
    ]

    text = await _format_order_details(
        FakeSession(Product(id=30, marketplace_commission_rate=Decimal("0.33"))),
        order,
        "Europe/Moscow",
    )

    assert "Комиссия маркетплейса: н/д" not in text
    assert "🚚 Логистика: 0 ₽" not in text
    assert "Базовая комиссия WB: 138 ₽ (33%, базовая)" in text
    assert "Логистика: 92 ₽ (базовая)" in text
    assert "Прибыль: -25 ₽" in text
    assert "Маржа: -5.90%" in text
