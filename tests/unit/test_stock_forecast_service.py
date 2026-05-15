"""version: 1.0.0
description: Unit tests for stockout forecast and lost revenue helpers.
updated: 2026-05-15
"""

from decimal import Decimal

from app.services.stock_forecast_service import (
    calculate_days_until_stockout,
    classify_stock_risk,
    estimate_lost_revenue,
)


def test_stockout_forecast_calculates_days_and_lost_revenue() -> None:
    days = calculate_days_until_stockout(quantity=10, average_daily_sales=Decimal("2"))
    lost_revenue = estimate_lost_revenue(
        days_until_stockout=days,
        horizon_days=30,
        average_daily_sales=Decimal("2"),
        average_price=Decimal("500"),
    )

    assert days == Decimal("5.0")
    assert lost_revenue == Decimal("25000.00")


def test_stockout_forecast_handles_zero_sales_without_division_by_zero() -> None:
    assert calculate_days_until_stockout(quantity=10, average_daily_sales=Decimal("0")) is None
    assert estimate_lost_revenue(
        days_until_stockout=None,
        horizon_days=30,
        average_daily_sales=Decimal("0"),
        average_price=Decimal("500"),
    ) == Decimal("0")
    status, recommendation = classify_stock_risk(10, None)
    assert status == "unknown"
    assert "Недостаточно" in recommendation
