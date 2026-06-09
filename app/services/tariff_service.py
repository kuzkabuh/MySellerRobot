"""version: 1.1.0
description: Compatibility facade. Moved to app.services.subscriptions.tariff_service.
updated: 2026-06-09
"""

from app.services.subscriptions.tariff_service import (  # noqa: F401
    TariffService,
)

__all__ = ['TariffService']
