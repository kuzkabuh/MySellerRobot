"""version: 1.0.0
description: Unit tests for Telegram message formatting.
updated: 2026-05-14
"""

from datetime import UTC, datetime
from decimal import Decimal

from app.models.enums import Marketplace, SaleModel
from app.schemas.orders import NormalizedOrder, NormalizedOrderItem
from app.schemas.profit import ProfitResult
from app.services.message_formatter import MessageFormatter


def test_new_order_card_contains_profit_and_missing_cost_warning() -> None:
    order = NormalizedOrder(
        marketplace=Marketplace.WB,
        order_external_id="1",
        order_date=datetime(2026, 5, 14, 12, 41, tzinfo=UTC),
        sale_model=SaleModel.FBS,
        status="new",
        warehouse="658434",
        items=[],
    )
    item = NormalizedOrderItem(
        title="Полотенце Fresh мятное",
        seller_article="FRESH-MINT-70",
        marketplace_article="123456789",
        discounted_price=Decimal("1490"),
        payout_amount_estimated=Decimal("1280"),
    )
    profit = ProfitResult(
        gross_revenue=Decimal("1490"),
        marketplace_commission=Decimal("256"),
        logistics_cost=Decimal("89"),
        acquiring_cost=Decimal("0"),
        storage_cost=Decimal("0"),
        return_cost=Decimal("0"),
        other_marketplace_costs=Decimal("18"),
        cost_price=Decimal("0"),
        package_cost=Decimal("25"),
        additional_seller_cost=Decimal("0"),
        tax_amount=Decimal("90"),
        profit=Decimal("282"),
        margin_percent=Decimal("22.0"),
        missing_cost=True,
    )

    text = MessageFormatter().new_order_card(order, item, profit, detailed=True)

    assert "Новый заказ" in text
    assert "Прибыль" in text
    assert "Себестоимость товара не указана" in text
