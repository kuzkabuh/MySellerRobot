"""version: 1.1.0
description: Unit tests for plan/fact deviation classification and rendering.
updated: 2026-05-20
"""

from datetime import UTC, datetime
from decimal import Decimal

from app.models.enums import Marketplace
from app.services.plan_fact_service import (
    PlanFactPageData,
    PlanFactRow,
    PlanFactSummary,
    classify_deviation,
)
from app.services.web_orders_profit_service import build_order_web_filters
from app.web.routes import _plan_fact_content


def test_classify_deviation_detects_missing_actual() -> None:
    reason = classify_deviation(
        estimated_profit=Decimal("100"),
        actual_profit=Decimal("0"),
        pending_actual=1,
        estimated_revenue=Decimal("500"),
        actual_revenue=Decimal("0"),
        estimated_marketplace_costs=Decimal("50"),
        actual_marketplace_costs=Decimal("0"),
    )

    assert reason == "факт ещё не получен"


def test_classify_deviation_detects_marketplace_cost_growth() -> None:
    reason = classify_deviation(
        estimated_profit=Decimal("100"),
        actual_profit=Decimal("40"),
        pending_actual=0,
        estimated_revenue=Decimal("500"),
        actual_revenue=Decimal("500"),
        estimated_marketplace_costs=Decimal("80"),
        actual_marketplace_costs=Decimal("140"),
    )

    assert reason == "расходы маркетплейса выше плана"


def test_plan_fact_content_renders_deviation_table() -> None:
    filters = build_order_web_filters(
        timezone="Europe/Moscow",
        period="30d",
        marketplace="all",
        sale_model="all",
        date_from=None,
        date_to=None,
        economy="all",
        status="all",
        sku="",
        sort="deviation",
        direction="asc",
    )
    data = PlanFactPageData(
        filters=filters,
        summary=PlanFactSummary(
            estimated_profit=Decimal("1000"),
            actual_profit=Decimal("760"),
            deviation=Decimal("-240"),
            deviation_percent=Decimal("-24.0"),
            orders=3,
            pending_actual=0,
        ),
        rows=[
            PlanFactRow(
                title="Полотенце Fresh",
                seller_article="TOWEL-1",
                marketplace=Marketplace.WB,
                sale_model=None,
                orders=3,
                estimated_profit=Decimal("1000"),
                actual_profit=Decimal("760"),
                deviation=Decimal("-240"),
                deviation_percent=Decimal("-24.0"),
                pending_actual=0,
                reason="расходы маркетплейса выше плана",
            )
        ],
    )

    html = _plan_fact_content(data)

    assert "Плановая прибыль" in html
    assert "Фактическая прибыль" in html
    assert "расходы маркетплейса выше плана" in html
    assert "-240 ₽" in html


def test_plan_fact_filters_keep_custom_period_dates() -> None:
    filters = build_order_web_filters(
        timezone="Europe/Moscow",
        period="custom",
        marketplace="WB",
        sale_model="FBS",
        date_from="2026-05-01",
        date_to="2026-05-15",
        economy="all",
        status="all",
        sku="",
        sort="deviation",
        direction="asc",
    )

    assert filters.date_from < datetime(2026, 5, 1, 22, 0, tzinfo=UTC)
    assert filters.marketplace == Marketplace.WB


def test_plan_fact_target_model_has_server_default_timestamps() -> None:
    """PlanFactTarget must have server_default on created_at and updated_at.

    Regression test for NotNullViolationError on plan_fact_targets.created_at.
    The server_default ensures the DB fills timestamps on INSERT.
    """
    from app.models.domain import PlanFactTarget

    created_at_col = PlanFactTarget.__table__.c.created_at
    updated_at_col = PlanFactTarget.__table__.c.updated_at

    assert (
        created_at_col.server_default is not None
    ), "created_at must have server_default to avoid NOT NULL violation"
    assert (
        updated_at_col.server_default is not None
    ), "updated_at must have server_default to avoid NOT NULL violation"
    assert created_at_col.nullable is False
    assert updated_at_col.nullable is False
