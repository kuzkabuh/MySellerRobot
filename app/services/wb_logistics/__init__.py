"""version: 1.1.0
description: Compatibility facade. Moved to app.services.wb.logistics.
updated: 2026-06-09
"""

from app.services.wb.logistics.wb_logistics_calculator_service import (  # noqa: F401
    WbLogisticsCalculatorService,
    WbLogisticsCalcResult,
)
from app.services.wb.logistics.wb_logistics_tariff_sync_service import (  # noqa: F401
    WbLogisticsTariffSyncService,
    TARIFF_SOURCE,
    WB_LOGISTICS_ERROR_MESSAGE,
)

__all__ = [
    "WbLogisticsCalculatorService",
    "WbLogisticsCalcResult",
    "WbLogisticsTariffSyncService",
    "TARIFF_SOURCE",
    "WB_LOGISTICS_ERROR_MESSAGE",
]
