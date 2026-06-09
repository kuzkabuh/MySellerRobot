"""version: 1.1.0
description: Compatibility facade. Moved to app.services.unit_economics.profit_calculator.
updated: 2026-06-09
"""

from app.services.unit_economics.profit_calculator import (  # noqa: F401
    ProfitCalculator,
    money,
)

__all__ = ['ProfitCalculator', 'money']
