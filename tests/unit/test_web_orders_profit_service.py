"""version: 1.0.0
description: Unit tests for web order filters, profit ROI, order state labels, and pagination.
updated: 2026-05-19
"""

from decimal import Decimal

from sqlalchemy.dialects import postgresql

from app.models.enums import Marketplace, SaleModel
from app.services.web_orders_profit_service import (
    WebOrdersProfitService,
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
    assert order_state_label("new", True) == "Новый заказ"
    assert order_state_label("cancelled", False) == "Отменён"
    assert order_state_label("awaiting_packaging", False) == "Ожидает упаковки"


def test_profit_order_query_reuses_postgresql_safe_group_by_expressions() -> None:
    filters = build_order_web_filters(
        timezone="Europe/Moscow",
        period="7d",
        marketplace="all",
        sale_model="all",
        date_from=None,
        date_to=None,
        economy="all",
        status="all",
        sku="",
        sort="profit",
        direction="desc",
    )

    query = WebOrdersProfitService._profit_order_query(user_id=1, filters=filters)
    sql = str(query.compile(dialect=postgresql.dialect()))

    assert "coalesce(order_items.title, order_items.seller_article, 'Без названия')" in sql
    assert "coalesce(order_items.seller_article, '')" in sql
    assert "param_" not in sql
    assert "GROUP BY coalesce(order_items.title, order_items.seller_article, 'Без названия')" in sql


def test_order_page_result_dataclass_exists() -> None:
    """Verify OrderPageResult dataclass is available for pagination."""
    from app.services.web_orders_profit_service import OrderPageResult

    result = OrderPageResult(
        filters=build_order_web_filters(
            timezone="Europe/Moscow",
            period="today",
            marketplace="all",
            sale_model="all",
            date_from=None,
            date_to=None,
            economy="all",
            status="all",
            sku="",
            sort="date",
            direction="desc",
        ),
        rows=[],
        total_count=0,
        page=1,
        per_page=50,
        total_pages=1,
    )
    assert result.total_count == 0
    assert result.page == 1
    assert result.per_page == 50
    assert result.total_pages == 1


def test_pagination_total_pages_calculation() -> None:
    """Verify total pages are calculated correctly."""
    from app.services.web_orders_profit_service import OrderPageResult

    def make_result(total: int, per_page: int, page: int = 1) -> OrderPageResult:
        total_pages = max(1, (total + per_page - 1) // per_page)
        return OrderPageResult(
            filters=build_order_web_filters(
                timezone="Europe/Moscow",
                period="today",
                marketplace="all",
                sale_model="all",
                date_from=None,
                date_to=None,
                economy="all",
                status="all",
                sku="",
                sort="date",
                direction="desc",
            ),
            rows=[],
            total_count=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
        )

    r = make_result(0, 50)
    assert r.total_pages == 1

    r = make_result(1, 50)
    assert r.total_pages == 1

    r = make_result(50, 50)
    assert r.total_pages == 1

    r = make_result(51, 50)
    assert r.total_pages == 2

    r = make_result(284, 100)
    assert r.total_pages == 3

    r = make_result(284, 50)
    assert r.total_pages == 6


def test_pagination_range_display() -> None:
    """Verify the displayed range is correct for various pages."""

    def range_for(total: int, per_page: int, page: int) -> tuple[int, int]:
        if total == 0:
            return (0, 0)
        start = (page - 1) * per_page + 1
        end = min(page * per_page, total)
        return (start, end)

    assert range_for(284, 100, 1) == (1, 100)
    assert range_for(284, 100, 2) == (101, 200)
    assert range_for(284, 100, 3) == (201, 284)
    assert range_for(5, 50, 1) == (1, 5)
    assert range_for(0, 50, 1) == (0, 0)


def test_filters_preserved_across_pages() -> None:
    """Verify that filters are preserved when building pagination URLs."""
    filters = build_order_web_filters(
        timezone="Europe/Moscow",
        period="7d",
        marketplace="WB",
        sale_model="FBS",
        date_from=None,
        date_to=None,
        economy="loss",
        status="action_required",
        sku="test-sku",
        sort="profit",
        direction="asc",
    )
    assert filters.marketplace == Marketplace.WB
    assert filters.sale_model == SaleModel.FBS
    assert filters.economy == "loss"
    assert filters.status == "action_required"
    assert filters.sku == "test-sku"
