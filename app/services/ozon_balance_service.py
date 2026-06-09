"""version: 1.1.0
description: Compatibility facade. Moved to app.services.ozon.finance.ozon_balance_service.
updated: 2026-06-09
"""

from app.services.ozon.finance.ozon_balance_service import (  # noqa: F401
    OzonBalanceService,
)

__all__ = ['OzonBalanceService']
