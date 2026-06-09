"""version: 1.1.0
description: Compatibility facade. Moved to app.services.unit_economics.stock_forecast_service.
updated: 2026-06-09
"""

from app.services.unit_economics.stock_forecast_service import (  # noqa: F401
    StockForecastRow,
    StockForecastService,
    calculate_days_until_stockout,
    classify_stock_risk,
    estimate_lost_revenue,
    stock_status_label,
    stock_status_tone,
)

__all__ = ['StockForecastRow', 'StockForecastService', 'calculate_days_until_stockout', 'classify_stock_risk', 'estimate_lost_revenue', 'stock_status_label', 'stock_status_tone']
