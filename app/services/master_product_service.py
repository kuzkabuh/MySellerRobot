"""version: 1.1.0
description: Compatibility facade. Moved to app.services.unit_economics.master_product_service.
updated: 2026-06-09
"""

from app.services.unit_economics.master_product_service import (  # noqa: F401
    MarketplaceComparisonRow,
    MarketplaceProductInfo,
    MasterProductAnalyticsRow,
    MasterProductDetail,
    MasterProductService,
    ProductMatchingCandidate,
    normalize_master_sku,
)

__all__ = ['MarketplaceComparisonRow', 'MarketplaceProductInfo', 'MasterProductAnalyticsRow', 'MasterProductDetail', 'MasterProductService', 'ProductMatchingCandidate', 'normalize_master_sku']
