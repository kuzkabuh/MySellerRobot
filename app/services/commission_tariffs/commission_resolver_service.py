"""version: 1.1.0
description: Unified commission rate resolver for WB and Ozon tariff lookups.
updated: 2026-05-20
"""

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commission_tariffs import (
    MarketplaceCommissionRate,
    MarketplaceCommissionVersion,
)
from app.models.enums import Marketplace

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CommissionResolutionResult:
    commission_percent: Decimal | None
    version_id: int | None
    source: str
    match_status: str
    matched_rate_id: int | None
    diagnostics: str
    commission_base_price: Decimal | None = None
    commission_amount: Decimal | None = None
    calculation_confidence: str = "not_available"


class CommissionResolverService:
    """Resolve commission rates from the tariff database.

    Priority:
    1. Exact match by category + sales model + price range (for Ozon)
    2. Match by category + sales model (for WB, which has flat rates per category)
    3. not_found — no rate found, no default applied
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_commission_rate(
        self,
        marketplace: str,
        order_date: date,
        sales_model: str,
        category_name: str | None = None,
        product_type_name: str | None = None,
        subject_name: str | None = None,
        product_price: Decimal | None = None,
        ozon_commission_base_price: Decimal | None = None,
    ) -> CommissionResolutionResult:
        """Resolve the commission rate for a given order context.

        Args:
            marketplace: "WB" or "OZON"
            order_date: date of the order (to select the correct tariff version)
            sales_model: "fbo", "fbs", "rfbs", etc.
            category_name: product category name
            product_type_name: product type (Ozon-specific)
            subject_name: WB subject name
            product_price: product price for Ozon price-range lookups
            ozon_commission_base_price: official Ozon commission base price
                (seller's set price per Ozon methodology)

        Returns:
            CommissionResolutionResult with the resolved rate or not_found.
        """
        mp = Marketplace(marketplace)
        sales_model_lower = sales_model.lower()

        version = await self._find_active_version(mp, order_date)
        if version is None:
            return CommissionResolutionResult(
                commission_percent=None,
                version_id=None,
                source="not_found",
                match_status="not_found",
                matched_rate_id=None,
                diagnostics="Нет активной версии тарифов",
                commission_base_price=ozon_commission_base_price or product_price,
                calculation_confidence="not_available",
            )

        # For Ozon, prefer ozon_commission_base_price over product_price
        effective_price = ozon_commission_base_price or product_price

        rate = await self._find_rate(
            version_id=version.id,
            marketplace=mp,
            sales_model=sales_model_lower,
            category_name=category_name,
            product_type_name=product_type_name,
            subject_name=subject_name,
            product_price=effective_price,
        )

        if rate is not None:
            commission_amount = None
            confidence = "exact"
            base_price = effective_price

            if mp == Marketplace.OZON:
                if ozon_commission_base_price is not None:
                    base_price = ozon_commission_base_price
                    confidence = "exact"
                elif product_price is not None:
                    confidence = "estimated"
                    base_price = product_price

                if base_price is not None:
                    commission_amount = (
                        base_price * rate.commission_percent / Decimal("100")
                    ).quantize(Decimal("0.01"))

            return CommissionResolutionResult(
                commission_percent=rate.commission_percent,
                version_id=version.id,
                source=f"{mp.value.lower()}_tariff_db",
                match_status="exact",
                matched_rate_id=rate.id,
                diagnostics=f"Найдена ставка: {rate.commission_percent}%",
                commission_base_price=base_price,
                commission_amount=commission_amount,
                calculation_confidence=confidence,
            )

        return CommissionResolutionResult(
            commission_percent=None,
            version_id=version.id,
            source="not_found",
            match_status="not_found",
            matched_rate_id=None,
            diagnostics="Тариф для категории не найден",
            commission_base_price=ozon_commission_base_price or product_price,
            calculation_confidence="not_available",
        )

    async def _find_active_version(
        self,
        marketplace: Marketplace,
        order_date: date,
    ) -> MarketplaceCommissionVersion | None:
        """Find the active tariff version valid on the given date."""
        result = await self.session.execute(
            select(MarketplaceCommissionVersion)
            .where(MarketplaceCommissionVersion.marketplace == marketplace)
            .where(MarketplaceCommissionVersion.is_active.is_(True))
            .where(MarketplaceCommissionVersion.effective_from <= order_date)
            .where(
                (MarketplaceCommissionVersion.effective_to.is_(None))
                | (MarketplaceCommissionVersion.effective_to >= order_date)
            )
            .order_by(MarketplaceCommissionVersion.effective_from.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _find_rate(
        self,
        *,
        version_id: int,
        marketplace: Marketplace,
        sales_model: str,
        category_name: str | None,
        product_type_name: str | None,
        subject_name: str | None,
        product_price: Decimal | None,
    ) -> MarketplaceCommissionRate | None:
        """Find a matching commission rate."""
        query = select(MarketplaceCommissionRate).where(
            MarketplaceCommissionRate.version_id == version_id,
            MarketplaceCommissionRate.marketplace == marketplace,
            MarketplaceCommissionRate.sales_model == sales_model,
        )

        if marketplace == Marketplace.OZON and product_price is not None:
            query = query.where(
                MarketplaceCommissionRate.price_from < product_price,
                (
                    (MarketplaceCommissionRate.price_to_inclusive.is_(True))
                    & (MarketplaceCommissionRate.price_to >= product_price)
                )
                | (
                    (MarketplaceCommissionRate.price_to_inclusive.is_(False))
                    & (MarketplaceCommissionRate.price_to > product_price)
                ),
            )

        if category_name:
            query = query.where(MarketplaceCommissionRate.category_name == category_name)

        if product_type_name:
            query = query.where(MarketplaceCommissionRate.product_type_name == product_type_name)
        elif subject_name:
            query = query.where(MarketplaceCommissionRate.subject_name == subject_name)

        result = await self.session.execute(query.limit(1))
        rate = result.scalar_one_or_none()

        if rate is None and category_name:
            query = select(MarketplaceCommissionRate).where(
                MarketplaceCommissionRate.version_id == version_id,
                MarketplaceCommissionRate.marketplace == marketplace,
                MarketplaceCommissionRate.sales_model == sales_model,
                MarketplaceCommissionRate.category_name == category_name,
            )
            if marketplace == Marketplace.OZON and product_price is not None:
                query = query.where(
                    MarketplaceCommissionRate.price_from < product_price,
                    (
                        (MarketplaceCommissionRate.price_to_inclusive.is_(True))
                        & (MarketplaceCommissionRate.price_to >= product_price)
                    )
                    | (
                        (MarketplaceCommissionRate.price_to_inclusive.is_(False))
                        & (MarketplaceCommissionRate.price_to > product_price)
                    ),
                )
            result = await self.session.execute(query.limit(1))
            rate = result.scalar_one_or_none()

        return rate
