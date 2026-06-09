"""version: 1.1.0
description: Compatibility facade. Moved to app.services.common.web_orders_profit_service.
updated: 2026-06-09
"""

from app.services.common.web_orders_profit_service import (  # noqa: F401
    OrderDetail,
    OrderDetailItem,
    OrderPageResult,
    OrderRow,
    OrderWebFilters,
    ProfitPageData,
    ProfitSkuRow,
    ProfitSummary,
    WbFactArticleState,
    WbOrderFact,
    WebOrdersProfitService,
    build_order_web_filters,
    localized_order_date,
    order_state_label,
    roi_percent,
)

__all__ = ['OrderDetail', 'OrderDetailItem', 'OrderPageResult', 'OrderRow', 'OrderWebFilters', 'ProfitPageData', 'ProfitSkuRow', 'ProfitSummary', 'WbFactArticleState', 'WbOrderFact', 'WebOrdersProfitService', 'build_order_web_filters', 'localized_order_date', 'order_state_label', 'roi_percent']
