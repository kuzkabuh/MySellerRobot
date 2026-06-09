"""version: 1.1.0
description: Compatibility facade. Moved to app.services.common.stock_service.
updated: 2026-06-09
"""

from app.services.common.stock_service import (  # noqa: F401
    StockService,
)

__all__ = ['StockService']
