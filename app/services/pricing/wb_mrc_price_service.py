"""version: 1.0.0
description: Wildberries MRC (recommended retail price) price calculation service.
updated: 2026-05-21
"""

import logging
import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, InvalidOperation

from app.core.config import get_settings
from app.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WbMrcPriceResult:
    """Result of MRC price calculation."""

    mrc_price: Decimal
    promo_required_price: Decimal | None
    final_discounted_price: Decimal
    price_before_discount: Decimal
    discount_percent: Decimal
    mrc_discount_rub: Decimal
    mrc_discount_percent: Decimal
    max_mrc_discount_percent: int
    is_promo_applied: bool
    is_limited_by_mrc_rule: bool
    is_limited_by_min_price: bool
    reason: str


class WbMrcPriceService:
    """Calculate WB seller price based on MRC (recommended retail price).

    MRC is the target selling price after discount. The service calculates
    the seller's price before discount that WB will display with a discount
    to reach the MRC target.

    Formula:
        price_before_discount = final_discounted_price * multiplier

    Rules:
        - If no promo: final_discounted_price = mrc_price
        - If promo exists and planPrice >= mrc_price - max_discount%:
          final_discounted_price = planPrice
        - If promo requires price below limit:
          final_discounted_price = ceil(mrc_price * (1 - max_discount% / 100))
        - If min_price is set and calculated price < min_price:
          final_discounted_price = min_price
    """

    def __init__(
        self,
        *,
        max_discount_percent: int | None = None,
        price_before_discount_multiplier: int | None = None,
    ) -> None:
        settings = get_settings()
        self.max_discount_percent = (
            max_discount_percent
            if max_discount_percent is not None
            else settings.wb_mrc_promo_max_discount_percent
        )
        self.price_before_discount_multiplier = (
            price_before_discount_multiplier
            if price_before_discount_multiplier is not None
            else settings.wb_price_before_discount_multiplier
        )

    def calculate(
        self,
        *,
        mrc_price: Decimal,
        promo_required_price: Decimal | None = None,
        min_price: Decimal | None = None,
        discount_percent: Decimal | None = None,
    ) -> WbMrcPriceResult:
        """Calculate WB seller price based on MRC.

        Args:
            mrc_price: Target selling price after discount (MRC).
            promo_required_price: planPrice from WB promotion nomenclature, if applicable.
            min_price: Minimum seller price that cannot be exceeded downward.
            discount_percent: Display discount percentage for WB (default 75).

        Returns:
            WbMrcPriceResult with full calculation details.

        Raises:
            ValidationError: If mrc_price is invalid.
        """
        mrc_price = self._validate_mrc_price(mrc_price)
        effective_discount = discount_percent or Decimal("75")

        # Step 1: Determine final discounted price
        final_discounted_price, is_promo_applied, is_limited_by_mrc_rule = (
            self._determine_final_price(mrc_price, promo_required_price)
        )

        # Step 2: Apply min_price constraint
        is_limited_by_min_price = False
        if min_price is not None and min_price > 0:
            try:
                min_price_decimal = Decimal(str(min_price))
            except (InvalidOperation, ValueError):
                min_price_decimal = None

            if min_price_decimal is not None and final_discounted_price < min_price_decimal:
                final_discounted_price = min_price_decimal
                is_limited_by_min_price = True

        # Step 3: Calculate price before discount
        price_before_discount = (
            final_discounted_price * Decimal(str(self.price_before_discount_multiplier))
        ).quantize(Decimal("1"), rounding=ROUND_CEILING)

        # Step 4: Calculate discount metrics
        mrc_discount_rub = mrc_price - final_discounted_price
        if mrc_price > 0:
            mrc_discount_percent = (mrc_discount_rub / mrc_price * Decimal("100")).quantize(
                Decimal("0.01")
            )
        else:
            mrc_discount_percent = Decimal("0")

        # Step 5: Determine reason
        reason = self._determine_reason(
            is_promo_applied=is_promo_applied,
            is_limited_by_mrc_rule=is_limited_by_mrc_rule,
            is_limited_by_min_price=is_limited_by_min_price,
            mrc_price=mrc_price,
            promo_required_price=promo_required_price,
            final_discounted_price=final_discounted_price,
            min_price=min_price,
        )

        result = WbMrcPriceResult(
            mrc_price=mrc_price,
            promo_required_price=promo_required_price,
            final_discounted_price=final_discounted_price,
            price_before_discount=price_before_discount,
            discount_percent=effective_discount,
            mrc_discount_rub=mrc_discount_rub,
            mrc_discount_percent=mrc_discount_percent,
            max_mrc_discount_percent=self.max_discount_percent,
            is_promo_applied=is_promo_applied,
            is_limited_by_mrc_rule=is_limited_by_mrc_rule,
            is_limited_by_min_price=is_limited_by_min_price,
            reason=reason,
        )

        logger.info(
            "wb_mrc_price_calculated",
            extra={
                "mrc_price": str(mrc_price),
                "promo_required_price": str(promo_required_price),
                "final_discounted_price": str(final_discounted_price),
                "price_before_discount": str(price_before_discount),
                "is_promo_applied": is_promo_applied,
                "is_limited_by_mrc_rule": is_limited_by_mrc_rule,
                "is_limited_by_min_price": is_limited_by_min_price,
                "reason": reason,
            },
        )

        return result

    def _validate_mrc_price(self, mrc_price: Decimal) -> Decimal:
        """Validate MRC price is positive."""
        if mrc_price is None:
            raise ValidationError("МРЦ не указана", field="mrc_price")
        try:
            mrc_price = Decimal(str(mrc_price))
        except (InvalidOperation, ValueError, TypeError):
            raise ValidationError("Некорректное значение МРЦ", field="mrc_price")
        if mrc_price <= 0:
            raise ValidationError("МРЦ должна быть больше нуля", field="mrc_price")
        return mrc_price

    def _determine_final_price(
        self,
        mrc_price: Decimal,
        promo_required_price: Decimal | None,
    ) -> tuple[Decimal, bool, bool]:
        """Determine the final discounted price based on MRC and promo.

        Returns:
            Tuple of (final_discounted_price, is_promo_applied, is_limited_by_mrc_rule)
        """
        if promo_required_price is None or promo_required_price <= 0:
            # No promo: final price = MRC
            return mrc_price, False, False

        # Calculate minimum allowed price: MRC - max_discount%
        max_discount_decimal = Decimal(str(self.max_discount_percent))
        min_allowed_price = mrc_price * (Decimal("1") - max_discount_decimal / Decimal("100"))

        # Round up to ensure we don't go below the limit
        min_allowed_price_rounded = Decimal(
            math.ceil(min_allowed_price)
        )

        promo_price = Decimal(str(promo_required_price))

        if promo_price >= min_allowed_price_rounded:
            # Promo price is within allowed range
            return promo_price, True, False
        else:
            # Promo price is below limit, use the minimum allowed
            return min_allowed_price_rounded, True, True

    @staticmethod
    def _determine_reason(
        *,
        is_promo_applied: bool,
        is_limited_by_mrc_rule: bool,
        is_limited_by_min_price: bool,
        mrc_price: Decimal,
        promo_required_price: Decimal | None,
        final_discounted_price: Decimal,
        min_price: Decimal | None,
    ) -> str:
        """Determine human-readable reason for the calculated price."""
        if is_limited_by_min_price:
            parts = []
            if is_limited_by_mrc_rule:
                parts.append(
                    "Цена акции ниже допустимого лимита МРЦ"
                )
            elif is_promo_applied:
                parts.append(
                    "Цена акции ниже минимальной цены продавца"
                )
            parts.append(
                f"Цена установлена на уровне minPrice ({min_price})"
            )
            return ". ".join(parts)

        if is_limited_by_mrc_rule:
            return "Цена акции ниже допустимого лимита, применено максимальное снижение от МРЦ"

        if is_promo_applied:
            return "Цена акции находится в допустимых пределах снижения МРЦ"

        return "Акции нет, цена установлена равной МРЦ"
