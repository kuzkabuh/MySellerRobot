"""version: 1.1.0
description: Compatibility facade. Moved to app.services.alerts.alert_service.
updated: 2026-06-09
"""

from app.services.alerts.alert_service import (  # noqa: F401
    AlertRecommendation,
    AlertService,
)

__all__ = ['AlertRecommendation', 'AlertService']
