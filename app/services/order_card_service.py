"""version: 1.1.0
description: Compatibility facade. Moved to app.services.unit_economics.order_card_service.
updated: 2026-06-09
"""

from app.services.unit_economics.order_card_service import (  # noqa: F401
    OrderCardService,
    OrderStats,
    VisualNotification,
)

__all__ = ['OrderCardService', 'OrderStats', 'VisualNotification']
