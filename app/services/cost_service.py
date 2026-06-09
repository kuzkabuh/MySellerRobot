"""version: 1.1.0
description: Compatibility facade. Moved to app.services.unit_economics.cost_service.
updated: 2026-06-09
"""

from app.services.unit_economics.cost_service import (  # noqa: F401
    CostService,
    choose_actual_cost,
)

__all__ = ['CostService', 'choose_actual_cost']
