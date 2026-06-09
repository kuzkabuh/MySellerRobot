"""version: 1.1.0
description: Compatibility facade. Moved to app.services.unit_economics.cost_management_service.
updated: 2026-06-09
"""

from app.services.unit_economics.cost_management_service import (  # noqa: F401
    CostImportResult,
    CostManagementError,
    CostManagementService,
    parse_manual_cost_line,
)

__all__ = ['CostImportResult', 'CostManagementError', 'CostManagementService', 'parse_manual_cost_line']
