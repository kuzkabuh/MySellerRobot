"""version: 1.1.0
description: Compatibility facade. Moved to app.services.ozon.api.ozon_catalog_enrichment_service.
updated: 2026-06-09
"""

from app.services.ozon.api.ozon_catalog_enrichment_service import (  # noqa: F401
    OzonCatalogEnrichmentService,
    OzonEnrichmentStats,
)

__all__ = ['OzonCatalogEnrichmentService', 'OzonEnrichmentStats']
