"""version: 1.0.0
description: WB logistics tariff sync service for /api/v1/tariffs/box.
updated: 2026-05-20
"""

import hashlib
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import MarketplaceApiError
from app.integrations.wb import WildberriesClient
from app.models.wb_logistics_tariffs import (
    WbLogisticsTariffRate,
    WbLogisticsTariffVersion,
)
from app.utils.datetime import get_moscow_today

logger = logging.getLogger(__name__)

TARIFF_SOURCE = "wb_api"
WB_LOGISTICS_ERROR_MESSAGE = (
    "Не удалось обновить тарифы логистики WB. "
    "Попробуйте позже или проверьте API-ключ."
)


def _compute_version_hash(payload: list[dict[str, Any]]) -> str:
    """Compute SHA-256 hash of normalized tariff payload for change detection."""
    normalized = sorted(json.dumps(entry, sort_keys=True, default=str) for entry in payload)
    combined = "\n".join(normalized).encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


def _parse_coefficient_expr(expr: str | None) -> Decimal | None:
    """Try to parse a simple coefficient expression like '1.2' or '1.20' into Decimal."""
    if not expr:
        return None
    try:
        cleaned = expr.strip().replace(",", ".")
        value = Decimal(cleaned)
        if value > 0:
            return value
    except Exception:
        pass
    return None


def _normalize_tariff_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalize a single tariff entry from WB API response."""
    warehouse_name = entry.get("warehouseName", "") or ""
    geo_name = entry.get("geoName")

    # FBO fields
    fbo_base = entry.get("boxDeliveryBase")
    fbo_liter = entry.get("boxDeliveryLiter")
    fbo_coef_expr = entry.get("boxDeliveryCoefExpr")

    # FBS fields
    fbs_base = entry.get("boxDeliveryMarketplaceBase")
    fbs_liter = entry.get("boxDeliveryMarketplaceLiter")
    fbs_coef_expr = entry.get("boxDeliveryMarketplaceCoefExpr")

    return {
        "warehouse_name": warehouse_name,
        "geo_name": geo_name,
        "fbo_base_tariff": _safe_decimal(fbo_base),
        "fbo_liter_tariff": _safe_decimal(fbo_liter),
        "fbo_coefficient_expr": str(fbo_coef_expr) if fbo_coef_expr is not None else None,
        "fbs_base_tariff": _safe_decimal(fbs_base),
        "fbs_liter_tariff": _safe_decimal(fbs_liter),
        "fbs_coefficient_expr": str(fbs_coef_expr) if fbs_coef_expr is not None else None,
        "logistics_coefficient_percent": _parse_coefficient_expr(fbo_coef_expr),
        "raw_payload": entry,
    }


def _safe_decimal(value: Any) -> Decimal | None:
    """Convert value to Decimal safely."""
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value).replace(",", "."))
        return result if result >= 0 else None
    except Exception:
        return None


class WbLogisticsTariffSyncService:
    """Syncs WB box delivery logistics tariffs from /api/v1/tariffs/box."""

    def __init__(
        self,
        session: AsyncSession,
        wb_client: WildberriesClient,
    ) -> None:
        self._session = session
        self._wb_client = wb_client

    async def sync(self, tariff_date: str | None = None) -> dict[str, Any]:
        """Fetch and store WB logistics tariffs.

        Returns dict with keys:
        - status: "new_version" | "no_changes" | "error"
        - version_id: int | None
        - rows_count: int
        - message: str
        """
        effective_date = tariff_date or get_moscow_today()
        try:
            raw_tariffs = await self._wb_client.get_box_tariffs(date=effective_date)
        except MarketplaceApiError as exc:
            payload = exc.details.get("payload") if isinstance(exc.details, dict) else None
            request_id = payload.get("requestId") if isinstance(payload, dict) else None
            logger.exception(
                "wb_logistics_tariffs_fetch_failed",
                extra={
                    "endpoint": "/api/v1/tariffs/box",
                    "status_code": exc.status_code,
                    "request_id": request_id,
                    "response_body": payload,
                    "tariff_date": effective_date,
                },
            )
            return {
                "status": "error",
                "version_id": None,
                "rows_count": 0,
                "message": WB_LOGISTICS_ERROR_MESSAGE,
            }
        except Exception:
            logger.exception(
                "wb_logistics_tariffs_fetch_failed",
                extra={"endpoint": "/api/v1/tariffs/box", "tariff_date": effective_date},
            )
            return {
                "status": "error",
                "version_id": None,
                "rows_count": 0,
                "message": WB_LOGISTICS_ERROR_MESSAGE,
            }

        if not raw_tariffs:
            return {
                "status": "error",
                "version_id": None,
                "rows_count": 0,
                "message": "Empty response from WB API",
            }

        payload_hash = _compute_version_hash(raw_tariffs)

        existing = await self._session.execute(
            select(WbLogisticsTariffVersion).where(
                WbLogisticsTariffVersion.version_hash == payload_hash,
            )
        )
        existing_version = existing.scalar_one_or_none()
        if existing_version:
            logger.info(
                "WB logistics tariffs unchanged (hash=%s)",
                payload_hash[:12],
            )
            return {
                "status": "no_changes",
                "version_id": existing_version.id,
                "rows_count": 0,
                "message": "Тарифы логистики WB не изменились",
            }

        normalized = [_normalize_tariff_entry(entry) for entry in raw_tariffs]

        version = WbLogisticsTariffVersion(
            tariff_date=effective_date,
            version_hash=payload_hash,
            source=TARIFF_SOURCE,
            rows_count=len(normalized),
            is_active=True,
            synced_at=datetime.now(UTC),
        )
        self._session.add(version)
        await self._session.flush()

        for entry in normalized:
            rate = WbLogisticsTariffRate(
                version_id=version.id,
                warehouse_name=entry["warehouse_name"],
                geo_name=entry["geo_name"],
                sales_model="FBO",
                fbo_base_tariff=entry["fbo_base_tariff"],
                fbo_liter_tariff=entry["fbo_liter_tariff"],
                fbo_coefficient_expr=entry["fbo_coefficient_expr"],
                logistics_coefficient_percent=entry["logistics_coefficient_percent"],
                raw_payload=entry["raw_payload"],
            )
            self._session.add(rate)

            rate_fbs = WbLogisticsTariffRate(
                version_id=version.id,
                warehouse_name=entry["warehouse_name"],
                geo_name=entry["geo_name"],
                sales_model="FBS",
                fbs_base_tariff=entry["fbs_base_tariff"],
                fbs_liter_tariff=entry["fbs_liter_tariff"],
                fbs_coefficient_expr=entry["fbs_coefficient_expr"],
                raw_payload=entry["raw_payload"],
            )
            self._session.add(rate_fbs)

        await self._deactivate_old_versions(version.id)
        await self._session.commit()

        logger.info(
            "WB logistics tariffs synced: version_id=%s, rows=%s",
            version.id,
            len(normalized),
        )
        return {
            "status": "new_version",
            "version_id": version.id,
            "rows_count": len(normalized),
            "message": f"Синхронизировано {len(normalized)} тарифов логистики WB",
        }

    async def _deactivate_old_versions(self, current_version_id: int) -> None:
        """Deactivate all versions except the current one."""
        result = await self._session.execute(
            select(WbLogisticsTariffVersion).where(
                WbLogisticsTariffVersion.is_active.is_(True),
                WbLogisticsTariffVersion.id != current_version_id,
            )
        )
        for version in result.scalars().all():
            version.is_active = False
