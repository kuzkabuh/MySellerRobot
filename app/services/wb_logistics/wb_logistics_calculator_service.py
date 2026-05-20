"""version: 1.0.0
description: WB logistics calculator for planned and reverse logistics.
updated: 2026-05-20
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EconomyConfidence, ExpenseSource
from app.models.wb_logistics_tariffs import (
    WbLogisticsTariffRate,
    WbLogisticsTariffVersion,
)

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
ONE = Decimal("1")
MIN_KGT_LOGISTICS = Decimal("1000")
MAX_KGT_LOGISTICS = Decimal("3000")
LITER_THRESHOLD = Decimal("1")

KGT_VOLUME_THRESHOLDS = {
    "MGT": Decimal("1000"),
    "SGT": Decimal("5000"),
    "KGT_PLUS": Decimal("5000"),
    "KBT": Decimal("10000"),
}


@dataclass(frozen=True)
class WBLogisticsCalculationResult:
    """Result of WB logistics calculation."""

    logistics_amount_planned: Decimal | None
    base_volume_tariff: Decimal | None
    warehouse_coefficient_percent: Decimal | None
    localization_index: Decimal | None
    sales_distribution_index_percent: Decimal | None
    sales_distribution_surcharge_amount: Decimal | None
    tariff_version_id: int | None
    tariff_rate_id: int | None
    confidence: str
    source: str
    diagnostics: str


def _quantize_2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _quantize_4(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _safe_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value).replace(",", "."))
        return result if result >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def _classify_volume_category(volume_liters: Decimal) -> str:
    """Classify product volume category for logistics calculation."""
    if volume_liters is None or volume_liters <= 0:
        return "unknown"
    if volume_liters <= KGT_VOLUME_THRESHOLDS["MGT"]:
        return "MGT"
    if volume_liters <= KGT_VOLUME_THRESHOLDS["SGT"]:
        return "SGT"
    return "KGT_PLUS"


def _calculate_base_volume_tariff(
    volume_liters: Decimal,
    base_tariff: Decimal,
    liter_tariff: Decimal,
) -> Decimal:
    """Calculate base volume tariff.

    For volume <= 1L: use base_tariff directly.
    For volume > 1L: base_tariff + (volume - 1) * liter_tariff.
    """
    if volume_liters <= LITER_THRESHOLD:
        return base_tariff
    additional_liters = volume_liters - LITER_THRESHOLD
    return base_tariff + (additional_liters * liter_tariff)


def _calculate_mgt_logistics(
    base_volume_tariff: Decimal,
    warehouse_coefficient: Decimal,
    localization_index: Decimal,
    price_before_discount: Decimal,
    sales_distribution_index: Decimal,
) -> Decimal:
    """Calculate MGT (small/medium) logistics.

    Formula:
    logistics = base_volume_tariff × warehouse_coefficient × localization_index
              + price_before_discount × sales_distribution_index
    """
    direct_logistics = base_volume_tariff * warehouse_coefficient * localization_index
    distribution_surcharge = price_before_discount * sales_distribution_index
    return direct_logistics + distribution_surcharge


def _calculate_kgt_logistics(
    base_volume_tariff: Decimal,
    warehouse_coefficient: Decimal,
) -> Decimal:
    """Calculate KGT+ / SGT / KBT logistics.

    For large items:
    - localization_index NOT applied
    - sales_distribution_index NOT applied
    - Result capped between MIN_KGT_LOGISTICS and MAX_KGT_LOGISTICS
    """
    logistics = base_volume_tariff * warehouse_coefficient
    if logistics < MIN_KGT_LOGISTICS:
        return MIN_KGT_LOGISTICS
    if logistics > MAX_KGT_LOGISTICS:
        return MAX_KGT_LOGISTICS
    return logistics


def _calculate_reverse_logistics(
    volume_liters: Decimal,
    base_tariff: Decimal,
    liter_tariff: Decimal,
) -> Decimal:
    """Calculate reverse logistics (returns).

    Only base volume tariff, no warehouse coefficient, no indices.
    """
    return _calculate_base_volume_tariff(volume_liters, base_tariff, liter_tariff)


class WbLogisticsCalculatorService:
    """Calculates planned WB logistics based on official tariff methodology."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def calculate_planned_wb_logistics(
        self,
        *,
        order_date: datetime,
        sales_model: str,
        warehouse_name: str | None,
        product_volume_liters: Decimal | None,
        product_price_before_wb_discount: Decimal | None,
        localization_index: Decimal | None = None,
        sales_distribution_index_percent: Decimal | None = None,
        volume_category: str | None = None,
    ) -> WBLogisticsCalculationResult:
        """Calculate planned WB logistics for an order item.

        Returns WBLogisticsCalculationResult with amount, confidence, and diagnostics.
        """
        if product_volume_liters is None or product_volume_liters <= 0:
            return WBLogisticsCalculationResult(
                logistics_amount_planned=None,
                base_volume_tariff=None,
                warehouse_coefficient_percent=None,
                localization_index=None,
                sales_distribution_index_percent=None,
                sales_distribution_surcharge_amount=None,
                tariff_version_id=None,
                tariff_rate_id=None,
                confidence=EconomyConfidence.NOT_AVAILABLE,
                source=ExpenseSource.FALLBACK_DEFAULT,
                diagnostics="Объём товара не указан — расчёт логистики невозможен",
            )

        if not warehouse_name:
            return WBLogisticsCalculationResult(
                logistics_amount_planned=None,
                base_volume_tariff=None,
                warehouse_coefficient_percent=None,
                localization_index=None,
                sales_distribution_index_percent=None,
                sales_distribution_surcharge_amount=None,
                tariff_version_id=None,
                tariff_rate_id=None,
                confidence=EconomyConfidence.NOT_AVAILABLE,
                source=ExpenseSource.FALLBACK_DEFAULT,
                diagnostics="Склад не указан — расчёт логистики невозможен",
            )

        tariff_rate, version_id = await self._find_tariff_rate(
            warehouse_name=warehouse_name,
            sales_model=sales_model,
            order_date=order_date,
        )

        if tariff_rate is None:
            return WBLogisticsCalculationResult(
                logistics_amount_planned=None,
                base_volume_tariff=None,
                warehouse_coefficient_percent=None,
                localization_index=None,
                sales_distribution_index_percent=None,
                sales_distribution_surcharge_amount=None,
                tariff_version_id=None,
                tariff_rate_id=None,
                confidence=EconomyConfidence.NOT_AVAILABLE,
                source=ExpenseSource.FALLBACK_DEFAULT,
                diagnostics=(
                    f"Тариф логистики WB для склада '{warehouse_name}' "
                    f"({sales_model}) не найден"
                ),
            )

        base_tariff, liter_tariff = self._get_tariff_values(tariff_rate, sales_model)
        if base_tariff is None:
            return WBLogisticsCalculationResult(
                logistics_amount_planned=None,
                base_volume_tariff=None,
                warehouse_coefficient_percent=None,
                localization_index=None,
                sales_distribution_index_percent=None,
                sales_distribution_surcharge_amount=None,
                tariff_version_id=version_id,
                tariff_rate_id=tariff_rate.id,
                confidence=EconomyConfidence.NOT_AVAILABLE,
                source=ExpenseSource.WB_LOGISTICS_TARIFF_API,
                diagnostics="Базовый тариф логистики отсутствует в ответе API",
            )

        volume_category = volume_category or _classify_volume_category(product_volume_liters)
        is_kgt = volume_category in ("SGT", "KGT_PLUS", "KBT")

        base_volume_tariff = _calculate_base_volume_tariff(
            product_volume_liters, base_tariff, liter_tariff or ZERO
        )

        warehouse_coefficient = tariff_rate.logistics_coefficient_percent or ONE

        if is_kgt:
            logistics = _calculate_kgt_logistics(base_volume_tariff, warehouse_coefficient)
            return WBLogisticsCalculationResult(
                logistics_amount_planned=_quantize_2(logistics),
                base_volume_tariff=_quantize_4(base_volume_tariff),
                warehouse_coefficient_percent=_quantize_4(warehouse_coefficient),
                localization_index=None,
                sales_distribution_index_percent=None,
                sales_distribution_surcharge_amount=None,
                tariff_version_id=version_id,
                tariff_rate_id=tariff_rate.id,
                confidence=EconomyConfidence.EXACT,
                source=ExpenseSource.WB_LOGISTICS_TARIFF_API,
                diagnostics=(
                    f"КГТ ({volume_category}), тариф по объёму × коэф. "
                    "склада, ограничен 1000–3000 ₽"
                ),
            )

        localization = localization_index or ONE
        distribution = sales_distribution_index_percent or ZERO

        has_localization = localization_index is not None
        has_distribution = sales_distribution_index_percent is not None

        if product_price_before_wb_discount is None:
            price_for_distribution = ZERO
            distribution_surcharge = ZERO
            confidence = EconomyConfidence.ESTIMATED
            diagnostics_parts = ["Цена до скидки WB неизвестна — ИРП не применён"]
        else:
            price_for_distribution = product_price_before_wb_discount
            distribution_surcharge = price_for_distribution * distribution
            confidence = (
                EconomyConfidence.EXACT
                if (has_localization and has_distribution)
                else EconomyConfidence.ESTIMATED
            )
            diagnostics_parts = []
            if not has_localization:
                diagnostics_parts.append("Индекс локализации неизвестен — использовано 1.0")
            if not has_distribution:
                diagnostics_parts.append("ИРП неизвестен — использован 0")

        logistics = _calculate_mgt_logistics(
            base_volume_tariff=base_volume_tariff,
            warehouse_coefficient=warehouse_coefficient,
            localization_index=localization,
            price_before_discount=price_for_distribution,
            sales_distribution_index=distribution,
        )

        if not diagnostics_parts:
            diagnostics_parts.append("Расчёт по полной формуле МГТ")

        return WBLogisticsCalculationResult(
            logistics_amount_planned=_quantize_2(logistics),
            base_volume_tariff=_quantize_4(base_volume_tariff),
            warehouse_coefficient_percent=_quantize_4(warehouse_coefficient),
            localization_index=_quantize_4(localization) if has_localization else None,
            sales_distribution_index_percent=(
                _quantize_4(distribution) if has_distribution else None
            ),
            sales_distribution_surcharge_amount=_quantize_2(distribution_surcharge),
            tariff_version_id=version_id,
            tariff_rate_id=tariff_rate.id,
            confidence=confidence,
            source=ExpenseSource.WB_LOGISTICS_TARIFF_API,
            diagnostics="; ".join(diagnostics_parts),
        )

    async def calculate_planned_wb_reverse_logistics(
        self,
        *,
        product_volume_liters: Decimal | None,
        warehouse_name: str | None,
        sales_model: str,
        order_date: datetime,
    ) -> WBLogisticsCalculationResult:
        """Calculate planned reverse logistics (returns).

        Only base volume tariff, no warehouse coefficient, no indices.
        """
        if product_volume_liters is None or product_volume_liters <= 0:
            return WBLogisticsCalculationResult(
                logistics_amount_planned=None,
                base_volume_tariff=None,
                warehouse_coefficient_percent=None,
                localization_index=None,
                sales_distribution_index_percent=None,
                sales_distribution_surcharge_amount=None,
                tariff_version_id=None,
                tariff_rate_id=None,
                confidence=EconomyConfidence.NOT_AVAILABLE,
                source=ExpenseSource.FALLBACK_DEFAULT,
                diagnostics="Объём товара не указан — расчёт обратной логистики невозможен",
            )

        tariff_rate, version_id = await self._find_tariff_rate(
            warehouse_name=warehouse_name,
            sales_model=sales_model,
            order_date=order_date,
        )

        if tariff_rate is None:
            return WBLogisticsCalculationResult(
                logistics_amount_planned=None,
                base_volume_tariff=None,
                warehouse_coefficient_percent=None,
                localization_index=None,
                sales_distribution_index_percent=None,
                sales_distribution_surcharge_amount=None,
                tariff_version_id=None,
                tariff_rate_id=None,
                confidence=EconomyConfidence.NOT_AVAILABLE,
                source=ExpenseSource.FALLBACK_DEFAULT,
                diagnostics="Тариф логистики WB не найден для обратной логистики",
            )

        base_tariff, liter_tariff = self._get_tariff_values(tariff_rate, sales_model)
        if base_tariff is None:
            return WBLogisticsCalculationResult(
                logistics_amount_planned=None,
                base_volume_tariff=None,
                warehouse_coefficient_percent=None,
                localization_index=None,
                sales_distribution_index_percent=None,
                sales_distribution_surcharge_amount=None,
                tariff_version_id=version_id,
                tariff_rate_id=tariff_rate.id,
                confidence=EconomyConfidence.NOT_AVAILABLE,
                source=ExpenseSource.WB_LOGISTICS_TARIFF_API,
                diagnostics="Базовый тариф логистики отсутствует",
            )

        reverse_amount = _calculate_reverse_logistics(
            product_volume_liters, base_tariff, liter_tariff or ZERO
        )

        return WBLogisticsCalculationResult(
            logistics_amount_planned=_quantize_2(reverse_amount),
            base_volume_tariff=_quantize_4(base_tariff),
            warehouse_coefficient_percent=None,
            localization_index=None,
            sales_distribution_index_percent=None,
            sales_distribution_surcharge_amount=None,
            tariff_version_id=version_id,
            tariff_rate_id=tariff_rate.id,
            confidence=EconomyConfidence.ESTIMATED,
            source=ExpenseSource.WB_LOGISTICS_TARIFF_API,
            diagnostics="Обратная логистика: только базовый тариф по объёму",
        )

    async def _find_tariff_rate(
        self,
        *,
        warehouse_name: str,
        sales_model: str,
        order_date: datetime,
    ) -> tuple[WbLogisticsTariffRate | None, int | None]:
        """Find the active tariff rate for a warehouse and sales model."""
        result = await self._session.execute(
            select(WbLogisticsTariffVersion)
            .where(WbLogisticsTariffVersion.is_active.is_(True))
            .order_by(WbLogisticsTariffVersion.tariff_date.desc())
            .limit(1)
        )
        version = result.scalar_one_or_none()
        if version is None:
            return None, None

        rate_result = await self._session.execute(
            select(WbLogisticsTariffRate).where(
                WbLogisticsTariffRate.version_id == version.id,
                WbLogisticsTariffRate.warehouse_name == warehouse_name,
                WbLogisticsTariffRate.sales_model == sales_model,
            )
        )
        rate = rate_result.scalar_one_or_none()
        return rate, version.id

    def _get_tariff_values(
        self,
        rate: WbLogisticsTariffRate,
        sales_model: str,
    ) -> tuple[Decimal | None, Decimal | None]:
        """Extract base and per-liter tariff values for the sales model."""
        if sales_model.upper() in ("FBS", "RFBS"):
            return rate.fbs_base_tariff, rate.fbs_liter_tariff
        return rate.fbo_base_tariff, rate.fbo_liter_tariff
