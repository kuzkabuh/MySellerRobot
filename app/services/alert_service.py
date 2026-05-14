"""version: 1.0.0
description: Alert rule evaluation service.
updated: 2026-05-14
"""

from decimal import Decimal

from app.models.enums import AlertType
from app.schemas.profit import ProfitResult


class AlertService:
    """Evaluate core alert rules from calculated order economics."""

    def evaluate_profit_alerts(
        self,
        result: ProfitResult,
        low_margin_threshold: Decimal = Decimal("10"),
    ) -> list[AlertType]:
        alerts: list[AlertType] = []
        if result.profit < 0:
            alerts.append(AlertType.LOSS_ORDER)
        if result.margin_percent < low_margin_threshold:
            alerts.append(AlertType.LOW_MARGIN)
        if result.missing_cost:
            alerts.append(AlertType.MISSING_COST)
        return alerts

    def is_low_stock(self, quantity: int, threshold: int) -> bool:
        return quantity <= threshold

    def is_stockout_risk(self, days_until_stockout: Decimal | None, threshold_days: int) -> bool:
        return days_until_stockout is not None and days_until_stockout <= Decimal(threshold_days)
