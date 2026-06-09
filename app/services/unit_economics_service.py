"""version: 1.1.0
description: Compatibility facade. Moved to app.services.unit_economics.unit_economics_service.
updated: 2026-06-09
"""

from app.services.unit_economics.unit_economics_service import (  # noqa: F401
    BreakEvenRow,
    UnitEconomicsService,
)

__all__ = ['BreakEvenRow', 'UnitEconomicsService']
