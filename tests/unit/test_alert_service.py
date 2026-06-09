"""version: 1.0.0
description: Unit tests for alert rules.
updated: 2026-05-14
"""

from decimal import Decimal

from app.models.enums import AlertType
from app.schemas.profit import ProfitResult
from app.services.alerts.alert_service import AlertService


def test_profit_alerts_detect_loss_low_margin_and_missing_cost() -> None:
    result = ProfitResult(
        gross_revenue=Decimal("1000"),
        marketplace_commission=Decimal("0"),
        logistics_cost=Decimal("0"),
        acquiring_cost=Decimal("0"),
        storage_cost=Decimal("0"),
        return_cost=Decimal("0"),
        other_marketplace_costs=Decimal("0"),
        cost_price=Decimal("0"),
        package_cost=Decimal("0"),
        additional_seller_cost=Decimal("0"),
        tax_amount=Decimal("0"),
        profit=Decimal("-10"),
        margin_percent=Decimal("-1"),
        missing_cost=True,
    )

    alerts = AlertService().evaluate_profit_alerts(result)

    assert AlertType.LOSS_ORDER in alerts
    assert AlertType.LOW_MARGIN in alerts
    assert AlertType.MISSING_COST in alerts


def test_stock_alerts() -> None:
    service = AlertService()

    assert service.is_low_stock(quantity=3, threshold=5)
    assert service.is_stockout_risk(Decimal("2.5"), threshold_days=3)
