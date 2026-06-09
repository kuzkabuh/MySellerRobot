"""version: 1.1.0
description: Compatibility facade. Moved to app.services.common.data_quality_service.
updated: 2026-06-09
"""

from app.services.common.data_quality_service import (  # noqa: F401
    DataQualityMetric,
    DataQualityReport,
    DataQualityService,
)

__all__ = ['DataQualityMetric', 'DataQualityReport', 'DataQualityService']
