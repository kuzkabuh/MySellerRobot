"""version: 1.1.0
description: Compatibility facade. Moved to app.services.subscriptions.feature_access_service.
updated: 2026-06-09
"""

from app.services.subscriptions.feature_access_service import (  # noqa: F401
    FeatureAccessResult,
    FeatureAccessService,
    FeatureCode,
)

__all__ = ['FeatureAccessResult', 'FeatureAccessService', 'FeatureCode']
