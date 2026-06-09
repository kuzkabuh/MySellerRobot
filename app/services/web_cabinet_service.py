"""version: 1.1.0
description: Compatibility facade. Moved to app.services.account.web_cabinet_service.
updated: 2026-06-09
"""

from app.services.account.web_cabinet_service import (  # noqa: F401
    AccountRow,
    AccountsPageData,
    ControlPageData,
    CostRow,
    CostsPageData,
    ProductCostDetail,
    ReturnRow,
    ReturnsPageData,
    SalesPageData,
    SalesRow,
    SubscriptionPageData,
    WebCabinetService,
    subscription_status,
)

__all__ = ['AccountRow', 'AccountsPageData', 'ControlPageData', 'CostRow', 'CostsPageData', 'ProductCostDetail', 'ReturnRow', 'ReturnsPageData', 'SalesPageData', 'SalesRow', 'SubscriptionPageData', 'WebCabinetService', 'subscription_status']
