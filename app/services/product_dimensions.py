"""version: 1.1.0
description: Compatibility facade. Moved to app.services.common.product_dimensions.
updated: 2026-06-09
"""

from app.services.common.product_dimensions import (  # noqa: F401
    calculate_volume_liters,
    decimal_or_none,
)

__all__ = ['calculate_volume_liters', 'decimal_or_none']
