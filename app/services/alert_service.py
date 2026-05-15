"""version: 1.1.0
description: Alert rule evaluation service for profit, stock, and data quality risks.
updated: 2026-05-15
"""

from dataclasses import dataclass
from decimal import Decimal

from app.models.enums import AlertType
from app.schemas.profit import ProfitResult
from app.services.data_quality_service import DataQualityMetric


@dataclass(slots=True)
class AlertRecommendation:
    alert_type: AlertType
    title: str
    message: str
    severity: str


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

    def evaluate_stock_forecast(
        self,
        *,
        quantity: int,
        days_until_stockout: Decimal | None,
        lost_revenue: Decimal,
    ) -> list[AlertRecommendation]:
        alerts: list[AlertRecommendation] = []
        if quantity <= 0:
            alerts.append(
                AlertRecommendation(
                    alert_type=AlertType.LOW_STOCK,
                    title="Товар закончился",
                    message="Остаток равен нулю. Проверьте поставку и доступность товара.",
                    severity="critical",
                )
            )
        if self.is_stockout_risk(days_until_stockout, threshold_days=7):
            alerts.append(
                AlertRecommendation(
                    alert_type=AlertType.STOCKOUT_FORECAST,
                    title="Риск out-of-stock",
                    message=(
                        f"Запас закончится примерно через {days_until_stockout} дн. "
                        f"Потенциальная упущенная выручка: {lost_revenue:.0f} ₽."
                    ),
                    severity="warning",
                )
            )
        return alerts

    def evaluate_data_quality(
        self,
        metrics: list[DataQualityMetric],
    ) -> list[AlertRecommendation]:
        alerts: list[AlertRecommendation] = []
        for metric in metrics:
            if metric.status == "ok":
                continue
            alerts.append(
                AlertRecommendation(
                    alert_type=(
                        AlertType.MISSING_COST
                        if "себестоимости" in metric.title.lower()
                        else AlertType.ORDERS_DROP
                    ),
                    title=metric.title,
                    message=metric.description,
                    severity=metric.status,
                )
            )
        return alerts
