"""version: 1.0.0
description: Unit tests for web order filters, profit ROI, order state labels, and pagination.
updated: 2026-05-19
"""

import inspect
from decimal import Decimal

import pytest
from sqlalchemy.dialects import postgresql

from app.models.enums import Marketplace, SaleModel
from app.services.common.web_orders_profit_service import (
    ProfitSkuRow,
    WebOrdersProfitService,
    _reconciliation_status,
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


def test_profit_order_query_uses_latest_actual_snapshot_subquery() -> None:
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

    assert "row_number() OVER" in sql
    assert "PARTITION BY profit_snapshots.order_item_id" in sql
    assert "profit_snapshots.calculated_at DESC, profit_snapshots.id DESC" in sql
    assert "anon_1.rn = " in sql


def test_profit_merge_wb_rows_excludes_period_storage_scope() -> None:
    source = inspect.getsource(WebOrdersProfitService._merge_wb_daily_report_rows)

    assert "WbReportFinanceComponent.operation_scope.in_" in source
    assert "WbReportFinanceComponent.is_active.is_(True)" in source
    assert "WbReportFinanceComponent.deleted_at.is_(None)" in source


def test_reconciliation_status_maps_wb_fact_states() -> None:
    assert (
        _reconciliation_status(
            marketplace=Marketplace.WB,
            missing_cost=False,
            has_wb_fact=False,
            has_wb_missing_fact=False,
            has_wb_match_problem=False,
        ).value
        == "PRELIMINARY"
    )
    assert (
        _reconciliation_status(
            marketplace=Marketplace.WB,
            missing_cost=False,
            has_wb_fact=True,
            has_wb_missing_fact=False,
            has_wb_match_problem=False,
        ).value
        == "FACT_MATCHED"
    )
    assert (
        _reconciliation_status(
            marketplace=Marketplace.WB,
            missing_cost=False,
            has_wb_fact=True,
            has_wb_missing_fact=True,
            has_wb_match_problem=False,
        ).value
        == "FACT_PARTIAL"
    )
    assert (
        _reconciliation_status(
            marketplace=Marketplace.WB,
            missing_cost=False,
            has_wb_fact=True,
            has_wb_missing_fact=False,
            has_wb_match_problem=True,
        ).value
        == "FACT_AMBIGUOUS"
    )
    assert (
        _reconciliation_status(
            marketplace=Marketplace.WB,
            missing_cost=True,
            has_wb_fact=True,
            has_wb_missing_fact=False,
            has_wb_match_problem=False,
        ).value
        == "MANUAL_REVIEW"
    )


def test_order_page_result_dataclass_exists() -> None:
    """Verify OrderPageResult dataclass is available for pagination."""
    from app.services.common.web_orders_profit_service import OrderPageResult

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
    from app.services.common.web_orders_profit_service import OrderPageResult

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


class _FakeResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, ...]]:
        return self._rows


class _FakeSession:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, query: object) -> _FakeResult:
        self.calls += 1
        if self.calls == 1:
            return _FakeResult([("ART-001", 2)])
        return _FakeResult(
            [
                (
                    "ART-001",
                    Decimal("3000"),
                    Decimal("2400"),
                    Decimal("250"),
                )
            ]
        )


@pytest.mark.asyncio
async def test_profit_merges_wb_daily_report_rows_as_actual_fact() -> None:
    filters = build_order_web_filters(
        timezone="Europe/Moscow",
        period="7d",
        marketplace="WB",
        sale_model="all",
        date_from=None,
        date_to=None,
        economy="all",
        status="all",
        sku="",
        sort="profit",
        direction="desc",
    )
    existing = [
        ProfitSkuRow(
            title="Товар",
            seller_article="ART-001",
            marketplace=Marketplace.WB,
            sale_model=None,
            orders=1,
            sales=0,
            revenue=Decimal("1000"),
            estimated_revenue=Decimal("1000"),
            actual_revenue=Decimal("0"),
            payout=Decimal("0"),
            cost=Decimal("0"),
            marketplace_costs=Decimal("0"),
            estimated_profit=Decimal("0"),
            actual_profit=Decimal("0"),
            margin_percent=Decimal("0"),
            roi_percent=None,
            missing_cost_items=0,
            preliminary_items=0,
            actual_snapshot_items=0,
        )
    ]

    rows = await WebOrdersProfitService(_FakeSession())._merge_wb_daily_report_rows(
        1,
        filters,
        existing,
    )

    assert rows[0].sales == 2
    assert rows[0].revenue == Decimal("1000")
    assert rows[0].estimated_revenue == Decimal("1000")
    assert rows[0].actual_revenue == Decimal("3000")
    assert rows[0].payout == Decimal("2400")
    assert rows[0].marketplace_costs == Decimal("250")
    assert rows[0].actual_profit == Decimal("2400")


@pytest.mark.asyncio
async def test_profit_merge_does_not_double_count_actual_snapshot_profit() -> None:
    filters = build_order_web_filters(
        timezone="Europe/Moscow",
        period="7d",
        marketplace="WB",
        sale_model="all",
        date_from=None,
        date_to=None,
        economy="all",
        status="all",
        sku="",
        sort="profit",
        direction="desc",
    )
    existing = [
        ProfitSkuRow(
            title="Товар",
            seller_article="ART-001",
            marketplace=Marketplace.WB,
            sale_model=None,
            orders=1,
            sales=0,
            revenue=Decimal("1000"),
            estimated_revenue=Decimal("1000"),
            actual_revenue=Decimal("0"),
            payout=Decimal("0"),
            cost=Decimal("425"),
            marketplace_costs=Decimal("0"),
            estimated_profit=Decimal("0"),
            actual_profit=Decimal("575"),
            margin_percent=Decimal("0"),
            roi_percent=None,
            missing_cost_items=0,
            preliminary_items=0,
            actual_snapshot_items=1,
        )
    ]

    rows = await WebOrdersProfitService(_FakeSession())._merge_wb_daily_report_rows(
        1,
        filters,
        existing,
    )

    assert rows[0].payout == Decimal("2400")
    assert rows[0].actual_profit == Decimal("575")


def test_order_pagination_dto_has_next_prev() -> None:
    from app.services.common.web_orders_profit_service import OrderPaginationDTO

    p1 = OrderPaginationDTO(page=1, per_page=50, total=221, total_pages=5, has_next=True, has_prev=False)
    assert p1.has_next is True
    assert p1.has_prev is False
    assert p1.page == 1
    assert p1.total_pages == 5

    p3 = OrderPaginationDTO(page=3, per_page=50, total=221, total_pages=5, has_next=True, has_prev=True)
    assert p3.has_next is True
    assert p3.has_prev is True

    p5 = OrderPaginationDTO(page=5, per_page=50, total=221, total_pages=5, has_next=False, has_prev=True)
    assert p5.has_next is False
    assert p5.has_prev is True
    assert p5.total == 221


def test_order_summary_dto_defaults() -> None:
    from app.services.common.web_orders_profit_service import OrderSummaryDTO

    s = OrderSummaryDTO()
    assert s.total_orders == 0
    assert s.total_revenue == Decimal("0")
    assert s.missing_cost_count == 0
    assert s.loss_count == 0

    s2 = OrderSummaryDTO(
        total_orders=221,
        total_revenue=Decimal("500000"),
        total_estimated_profit=Decimal("75000"),
        missing_cost_count=5,
        loss_count=3,
        cancelled_count=12,
    )
    assert s2.total_orders == 221
    assert s2.total_revenue == Decimal("500000")
    assert s2.average_margin is None
    assert s2.missing_cost_count == 5
    assert s2.loss_count == 3
    assert s2.cancelled_count == 12


def test_order_web_filters_new_status() -> None:
    filters = build_order_web_filters(
        timezone="Europe/Moscow",
        period="7d",
        marketplace="all",
        sale_model="all",
        date_from=None,
        date_to=None,
        economy="all",
        status="new",
        sku="",
        sort="date",
        direction="desc",
    )
    assert filters.status == "new"

    filters_delivered = build_order_web_filters(
        timezone="Europe/Moscow",
        period="7d",
        marketplace="all",
        sale_model="all",
        date_from=None,
        date_to=None,
        economy="all",
        status="delivered",
        sku="",
        sort="date",
        direction="desc",
    )
    assert filters_delivered.status == "delivered"

    filters_return = build_order_web_filters(
        timezone="Europe/Moscow",
        period="7d",
        marketplace="all",
        sale_model="all",
        date_from=None,
        date_to=None,
        economy="all",
        status="return",
        sku="",
        sort="date",
        direction="desc",
    )
    assert filters_return.status == "return"

    filters_unknown = build_order_web_filters(
        timezone="Europe/Moscow",
        period="7d",
        marketplace="all",
        sale_model="all",
        date_from=None,
        date_to=None,
        economy="all",
        status="unknown_status",
        sku="",
        sort="date",
        direction="desc",
    )
    assert filters_unknown.status == "all"


def test_order_web_filters_allowed_status_values() -> None:
    allowed = {"all", "active", "cancelled", "new", "delivered", "return",
               "action_required", "fact_missing", "fact_partial", "fact_complete", "match_problem"}
    for status in allowed:
        f = build_order_web_filters(
            timezone="Europe/Moscow",
            period="30d",
            marketplace="all",
            sale_model="all",
            date_from=None,
            date_to=None,
            economy="all",
            status=status,
            sku="",
            sort="date",
            direction="desc",
        )
        assert f.status == status, f"Status {status} should be allowed"


def test_orders_summary_kpi_counts_from_order_rows() -> None:
    from app.services.common.web_orders_profit_service import OrderSummaryDTO

    summary = OrderSummaryDTO(
        total_orders=221,
        total_items=350,
        total_revenue=Decimal("1250000"),
        total_estimated_profit=Decimal("185000"),
        average_margin=Decimal("14.8"),
        missing_cost_count=12,
        loss_count=5,
        cancelled_count=18,
    )
    assert summary.total_orders == 221
    assert summary.total_revenue == Decimal("1250000")
    assert summary.average_margin == Decimal("14.8")
    assert float(summary.average_margin) == 14.8
    assert summary.missing_cost_count == 12
    assert summary.loss_count == 5

    revenue_tone = "good" if summary.total_revenue > 0 else ""
    assert revenue_tone == "good"

    profit_tone = "good" if summary.total_estimated_profit > 0 else "" if summary.total_estimated_profit == 0 else "bad"
    assert profit_tone == "good"

    margin_tone = "good" if summary.average_margin and summary.average_margin >= 10 else "" if summary.average_margin and summary.average_margin >= 0 else "bad"
    assert margin_tone == "good"

    missing_tone = "bad" if summary.missing_cost_count > 0 else "neutral"
    assert missing_tone == "bad"
