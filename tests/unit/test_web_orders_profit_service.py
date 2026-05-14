"""version: 1.0.0
description: Unit tests for web order filters, profit ROI, and order state labels.
updated: 2026-05-15
"""

from decimal import Decimal

from app.models.enums import Marketplace, SaleModel
from app.services.web_orders_profit_service import (
    build_order_web_filters,
    order_state_label,
    roi_percent,
)


def test_order_web_filters_parse_common_values() -> None:
    filters = build_order_web_filters(
        timezone="Europe/Moscow",
        period="7d",
        marketplace="WB",
        sale_model="FBO",
        date_from=None,
        date_to=None,
        economy="loss",
        status="action_required",
        sku=" SKU-001 ",
        sort="profit",
        direction="asc",
    )

    assert filters.period == "7d"
    assert filters.marketplace == Marketplace.WB
    assert filters.sale_model == SaleModel.FBO
    assert filters.economy == "loss"
    assert filters.status == "action_required"
    assert filters.sku == "SKU-001"
    assert filters.sort == "profit"
    assert filters.direction == "asc"


def test_order_web_filters_fall_back_from_unknown_values() -> None:
    filters = build_order_web_filters(
        timezone="Europe/Moscow",
        period="unknown",
        marketplace="bad",
        sale_model="bad",
        date_from=None,
        date_to=None,
        economy="bad",
        status="bad",
        sku="",
        sort="bad",
        direction="bad",
    )

    assert filters.period == "today"
    assert filters.marketplace is None
    assert filters.sale_model is None
    assert filters.economy == "all"
    assert filters.status == "all"
    assert filters.sort == "date"
    assert filters.direction == "desc"


def test_roi_percent_uses_cost_base() -> None:
    assert roi_percent(Decimal("250"), Decimal("500")) == Decimal("50.0")
    assert roi_percent(Decimal("-25"), Decimal("500")) == Decimal("-5.0")
    assert roi_percent(Decimal("100"), Decimal("0")) is None


def test_order_state_label_prefers_action_required_and_cancelled() -> None:
    assert order_state_label("new", True) == "требует действия"
    assert order_state_label("cancelled", False) == "отменён"
    assert order_state_label("awaiting_packaging", False) == "информационный"
