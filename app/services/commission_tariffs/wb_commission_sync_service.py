"""version: 1.1.0
description: Wildberries commission tariff sync service via official API.
updated: 2026-05-20
"""

import hashlib
import json
import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.integrations.wb import WildberriesClient
from app.models.commission_tariffs import (
    MarketplaceCommissionRate,
    MarketplaceCommissionVersion,
)
from app.models.enums import Marketplace

logger = logging.getLogger(__name__)

# Mapping of WB API commission fields to internal sales_model names.
# Official WB API fields (from GET /api/v1/tariffs/commission):
#   kgvpBooking        → комиссия «Бронирование»
#   kgvpMarketplace    → комиссия FBS («Маркетплейс»)
#   kgvpPickup         → комиссия «Самовывоз» (C&C)
#   kgvpSupplier       → комиссия DBS/DBW («Витрина» / «Курьер WB»)
#   kgvpSupplierExpress→ комиссия EDBS («Витрина экспресс»)
#   paidStorageKgvp    → комиссия FBW / «Склад WB»
#
# Internal project uses "fbo" as the canonical name for the warehouse model.
# WB officially calls it FBW / «Склад WB», but we map it to "fbo" internally
# for consistency with SaleModel.FBO used throughout the codebase.
WB_COMMISSION_FIELD_MAP: dict[str, str] = {
    "kgvpBooking": "booking",
    "kgvpMarketplace": "fbs",
    "kgvpPickup": "pickup",
    "kgvpSupplier": "dbs_dbw",
    "kgvpSupplierExpress": "edbs",
    "paidStorageKgvp": "fbo",
}


def _compute_payload_hash(payload: list[dict[str, Any]]) -> str:
    normalised = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _safe_decimal(value: Any) -> Decimal:
    """Convert a value to Decimal, returning 0 on failure."""
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _normalize_wb_tariff_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize a single WB tariff API report entry into rate records.

    The WB API returns a flat report array where each entry contains multiple
    commission fields for different sales models:

    {
        "kgvpBooking": 14.5,
        "kgvpMarketplace": 15.5,
        "kgvpPickup": 14.5,
        "kgvpSupplier": 12.5,
        "kgvpSupplierExpress": 3,
        "paidStorageKgvp": 15.5,
        "parentID": 657,
        "parentName": "Бытовая техника",
        "subjectID": 6461,
        "subjectName": "Оборудование зуботехническое"
    }

    Each non-null commission field becomes a separate MarketplaceCommissionRate.
    """
    rates = []

    parent_name = entry.get("parentName", "")
    parent_id = entry.get("parentID")
    subject_name = entry.get("subjectName", "")
    subject_id = entry.get("subjectID")

    category = parent_name or subject_name or ""

    for api_field, internal_model in WB_COMMISSION_FIELD_MAP.items():
        raw_value = entry.get(api_field)
        if raw_value is None:
            continue

        commission_percent = _safe_decimal(raw_value)

        rates.append({
            "category_name": str(category)[:512],
            "subject_name": str(subject_name)[:512] if subject_name else None,
            "object_name": None,
            "product_type_name": None,
            "sales_model": internal_model,
            "price_from": Decimal("0"),
            "price_to": Decimal("0"),
            "price_to_inclusive": False,
            "commission_percent": commission_percent,
            "raw_payload": {
                api_field: raw_value,
                "parentID": parent_id,
                "parentName": parent_name,
                "subjectID": subject_id,
                "subjectName": subject_name,
            },
        })

    return rates


class WbCommissionSyncService:
    """Sync WB commission tariffs from the official API."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def sync(self, api_key: str) -> dict[str, Any]:
        """Fetch tariffs from WB API and persist if changed.

        Returns a summary dict with sync results.
        """
        logger.info("wb_commission_sync_started")
        client = WildberriesClient(api_key)

        # Deactivate any empty versions from previous buggy syncs
        cleaned = await self.cleanup_empty_versions()
        if cleaned:
            logger.info("wb_commission_cleanup_deactivated", extra={"count": cleaned})

        try:
            raw_tariffs = await client.get_commission_tariffs()
        except Exception as exc:
            logger.exception(
                "wb_commission_sync_failed",
                extra={"error_type": type(exc).__name__, "error": str(exc)[:500]},
            )
            return {
                "success": False,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
            }

        payload_hash = _compute_payload_hash(raw_tariffs)
        active_version = await self._get_active_version()

        if active_version and active_version.source_file_sha256 == payload_hash:
            logger.info("wb_commission_sync_no_changes")
            return {
                "success": True,
                "changed": False,
                "message": "Комиссии WB не изменились",
                "version_id": active_version.id,
            }

        if not raw_tariffs:
            logger.error("wb_commission_sync_empty_report")
            return {
                "success": False,
                "error_type": "WBCommissionEmptyReportError",
                "error": "WB API вернул пустой report — тарифы не получены",
            }

        normalized_rates = []
        for entry in raw_tariffs:
            if isinstance(entry, dict):
                normalized_rates.extend(_normalize_wb_tariff_entry(entry))

        if not normalized_rates:
            logger.error(
                "wb_commission_sync_parse_failed",
                extra={"entries_count": len(raw_tariffs)},
            )
            return {
                "success": False,
                "error_type": "WBCommissionParseError",
                "error": (
                    f"WB API вернул {len(raw_tariffs)} записей, "
                    "но ни одна комиссия не была распознана"
                ),
            }

        if active_version:
            active_version.is_active = False
            active_version.effective_to = date.today()
            self.session.add(active_version)

        new_version = MarketplaceCommissionVersion(
            marketplace=Marketplace.WB,
            version_label=f"WB tariffs sync {date.today().isoformat()}",
            effective_from=date.today(),
            effective_to=None,
            source_type="wb_api",
            source_url=f"{get_settings().wb_base_common_url}/api/v1/tariffs/commission",
            source_file_name=None,
            source_file_sha256=payload_hash,
            imported_by_user_id=None,
            is_active=True,
            imported_at=datetime.now(tz=UTC),
        )
        self.session.add(new_version)
        await self.session.flush()

        for rate_data in normalized_rates:
            rate = MarketplaceCommissionRate(
                version_id=new_version.id,
                marketplace=Marketplace.WB,
                **rate_data,
            )
            self.session.add(rate)

        await self.session.commit()

        logger.info(
            "wb_commission_sync_finished",
            extra={
                "version_id": new_version.id,
                "rates_count": len(normalized_rates),
                "changed": True,
            },
        )

        return {
            "success": True,
            "changed": True,
            "version_id": new_version.id,
            "version_label": new_version.version_label,
            "rates_count": len(normalized_rates),
            "message": (
                f"Обновлены комиссии Wildberries. "
                f"Версия: {new_version.version_label}. "
                f"Ставок: {len(normalized_rates)}."
            ),
        }

    async def _get_active_version(self) -> MarketplaceCommissionVersion | None:
        result = await self.session.execute(
            select(MarketplaceCommissionVersion)
            .where(MarketplaceCommissionVersion.marketplace == Marketplace.WB)
            .where(MarketplaceCommissionVersion.is_active.is_(True))
            .order_by(MarketplaceCommissionVersion.effective_from.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def cleanup_empty_versions(self) -> int:
        """Deactivate any active WB versions that have 0 rates.

        This handles the case where a previous buggy sync created an empty version.
        Returns the number of versions deactivated.
        """
        result = await self.session.execute(
            select(MarketplaceCommissionVersion)
            .where(MarketplaceCommissionVersion.marketplace == Marketplace.WB)
            .where(MarketplaceCommissionVersion.is_active.is_(True))
        )
        empty_count = 0
        for version in result.scalars().all():
            rates_result = await self.session.execute(
                select(MarketplaceCommissionRate).where(
                    MarketplaceCommissionRate.version_id == version.id
                ).limit(1)
            )
            if rates_result.scalar_one_or_none() is None:
                version.is_active = False
                version.effective_to = date.today()
                empty_count += 1
                logger.warning(
                    "wb_commission_cleanup_empty_version",
                    extra={"version_id": version.id},
                )
        return empty_count
