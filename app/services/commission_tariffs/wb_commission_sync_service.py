"""version: 1.0.0
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

WB_SALES_MODEL_MAP: dict[str, str] = {
    "fbo": "fbo",
    "fbs": "fbs",
    "dbs": "dbs",
    "rfbs": "rfbs",
    "kvv": "fbo",
}


def _compute_payload_hash(payload: list[dict[str, Any]]) -> str:
    normalised = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _normalize_wb_tariff_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize a single WB tariff API entry into rate records."""
    rates = []
    subject = entry.get("subject", entry.get("subjectName", ""))
    object_name = entry.get("objectName", "")
    category = entry.get("categoryName", subject or "")

    tariffs = entry.get("tariffs", [])
    if not isinstance(tariffs, list):
        tariffs = [tariffs] if tariffs else []

    for tariff in tariffs:
        sales_model_raw = (tariff.get("salesModel") or tariff.get("type") or "").lower()
        sales_model = WB_SALES_MODEL_MAP.get(sales_model_raw, sales_model_raw)
        if not sales_model:
            sales_model = "fbo"

        percent_raw = tariff.get("commissionPercent", tariff.get("percent", 0))
        try:
            commission_percent = Decimal(str(percent_raw))
        except Exception:
            commission_percent = Decimal("0")

        rates.append({
            "category_name": str(category)[:512],
            "subject_name": str(subject)[:512] if subject else None,
            "object_name": str(object_name)[:512] if object_name else None,
            "product_type_name": None,
            "sales_model": sales_model,
            "price_from": Decimal("0"),
            "price_to": Decimal("0"),
            "price_to_inclusive": False,
            "commission_percent": commission_percent,
            "raw_payload": tariff,
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

        normalized_rates = []
        for entry in raw_tariffs:
            if isinstance(entry, dict):
                normalized_rates.extend(_normalize_wb_tariff_entry(entry))

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
