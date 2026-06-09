"""version: 1.1.0
description: Compatibility facade. Moved to app.services.common.order_processing_service.
updated: 2026-06-09
"""

from app.services.common.order_processing_service import (  # noqa: F401
    NewOrderNotification,
    OrderPollResult,
    OrderProcessingService,
)

__all__ = ['NewOrderNotification', 'OrderPollResult', 'OrderProcessingService']
