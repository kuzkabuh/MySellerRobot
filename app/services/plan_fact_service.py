"""version: 1.1.0
description: Compatibility facade. Moved to app.services.unit_economics.plan_fact_service.
updated: 2026-06-09
"""

from app.services.unit_economics.plan_fact_service import (  # noqa: F401
    PlanFactPageData,
    PlanFactRow,
    PlanFactService,
    PlanFactSummary,
    classify_deviation,
)

__all__ = ['PlanFactPageData', 'PlanFactRow', 'PlanFactService', 'PlanFactSummary', 'classify_deviation']
