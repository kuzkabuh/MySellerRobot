"""version: 1.0.0
description: Unit tests for web dashboard filters and rendering helpers.
updated: 2026-05-15
"""

from datetime import date
from decimal import Decimal

from app.models.enums import Marketplace, SaleModel
from app.services.common.web_dashboard_service import (
    DailyPoint,
    MarketplaceBreakdown,
    build_dashboard_filters,
    parse_marketplace,
    parse_sale_model,
    percent_change,
)
from app.web.routes import _bar_chart, _marketplace_table


def test_dashboard_filter_parses_marketplace_sale_model_and_period() -> None:
    filters = build_dashboard_filters(
        timezone="Europe/Moscow",
        period="custom",
        marketplace="WB",
        sale_model="rFBS",
        date_from="2026-05-13",
        date_to="2026-05-14",
    )

    assert filters.period == "custom"
    assert filters.marketplace == Marketplace.WB
    assert filters.sale_model == SaleModel.RFBS
    assert filters.local_date_from == date(2026, 5, 13)
    assert filters.local_date_to == date(2026, 5, 14)
    assert filters.date_from.date() == date(2026, 5, 12)


def test_dashboard_filter_ignores_unknown_values() -> None:
    assert parse_marketplace("unknown") is None
    assert parse_sale_model("unknown") is None


def test_percent_change_handles_zero_base() -> None:
    assert percent_change(Decimal("0"), Decimal("0")) == Decimal("0")
    assert percent_change(Decimal("10"), Decimal("0")) is None
    assert percent_change(Decimal("120"), Decimal("100")) == Decimal("20.0")


def test_bar_chart_renders_empty_state_for_zero_series() -> None:
    html = _bar_chart([DailyPoint(label="15.05")], "revenue", "Выручка", "#0f6f8f")

    assert "Данных за выбранный период пока нет" in html


def test_marketplace_table_keeps_wb_and_ozon_rows() -> None:
    data = type(
        "DashboardDataLike",
        (),
        {
            "marketplace_breakdown": [
                MarketplaceBreakdown(marketplace=Marketplace.WB, orders=2, sales=1),
                MarketplaceBreakdown(marketplace=Marketplace.OZON, orders=3, sales=2),
            ]
        },
    )()

    html = _marketplace_table(data)  # type: ignore[arg-type]

    assert "Wildberries" in html
    assert "Ozon" in html
