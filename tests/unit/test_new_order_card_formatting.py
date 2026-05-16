"""version: 1.0.0
description: Unit tests for new order Telegram card HTML safety and structure.
updated: 2026-05-17
"""

from datetime import UTC, datetime
from decimal import Decimal

from app.models.enums import Marketplace, SaleModel
from app.schemas.orders import NormalizedOrder, NormalizedOrderItem
from app.schemas.profit import ProfitResult
from app.services.message_formatter import MessageFormatter


def test_new_order_card_escapes_product_values_and_keeps_sections() -> None:
    order = NormalizedOrder(
        marketplace=Marketplace.WB,
        order_external_id="5055378321",
        order_date=datetime(2026, 5, 16, 18, 19, tzinfo=UTC),
        sale_model=SaleModel.FBS,
        status="new",
        normalized_status="new",
        warehouse="Склад <А>",
        deadline_at=None,
        processing_deadline_at=None,
        requires_seller_action=True,
        source_event_type=None,
        raw_payload={},
        items=[],
    )
    item = NormalizedOrderItem(
        title="Крем <новый> & тест",
        seller_article="SKU<1>",
        marketplace_article="WB&1",
        quantity=1,
        seller_price=Decimal("1490"),
        discounted_price=Decimal("1490"),
        payout_amount_estimated=Decimal("1200"),
    )
    profit = ProfitResult(
        gross_revenue=Decimal("1490"),
        expected_payout=Decimal("1200"),
        cost_price=Decimal("500"),
        package_cost=Decimal("0"),
        additional_seller_cost=Decimal("0"),
        marketplace_commission=Decimal("200"),
        logistics_cost=Decimal("100"),
        acquiring_cost=Decimal("0"),
        storage_cost=Decimal("0"),
        return_cost=Decimal("0"),
        other_marketplace_costs=Decimal("0"),
        tax_amount=Decimal("72"),
        profit=Decimal("328"),
        margin_percent=Decimal("22.0"),
        missing_cost=False,
        warnings=[],
    )

    text = MessageFormatter().new_order_card(order, item, profit, timezone_name="Europe/Moscow")

    assert "Новый заказ" in text
    assert "📊 Плановый результат:" in text
    assert "Крем &lt;новый&gt; &amp; тест" in text
    assert "SKU&lt;1&gt;" in text
    assert "<новый>" not in text
