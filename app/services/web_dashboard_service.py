"""version: 1.1.0
description: Compatibility facade. Moved to app.services.common.web_dashboard_service.
updated: 2026-06-09
"""

from app.services.common.web_dashboard_service import (  # noqa: F401
    DailyPoint,
    DashboardData,
    DashboardEvent,
    DashboardFilters,
    KpiMetric,
    MarketplaceBreakdown,
    WebDashboardService,
    build_dashboard_filters,
    is_cancelled_status,
    parse_marketplace,
    parse_sale_model,
    percent_change,
)

__all__ = ['DailyPoint', 'DashboardData', 'DashboardEvent', 'DashboardFilters', 'KpiMetric', 'MarketplaceBreakdown', 'WebDashboardService', 'build_dashboard_filters', 'is_cancelled_status', 'parse_marketplace', 'parse_sale_model', 'percent_change']
