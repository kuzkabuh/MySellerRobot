"""version: 1.0.0
description: User-configurable MRC pricing settings service.
updated: 2026-05-22
"""

import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import MrcPricingSettings

logger = logging.getLogger(__name__)

DEFAULT_DISCOUNT_PERCENT = Decimal("75.00")
DEFAULT_FULL_PRICE_MULTIPLIER = Decimal("4.00")
DEFAULT_ALLOWED_DEVIATION_PERCENT = Decimal("10.00")


@dataclass(slots=True)
class MrcSettingsResult:
    default_discount_percent: Decimal
    full_price_multiplier: Decimal
    allowed_action_price_deviation_percent: Decimal
    auto_promo_check_enabled: bool
    auto_add_to_promotions: bool
    auto_price_for_auto_promotions: bool
    is_default: bool


class MrcPricingSettingsService:
    """Manage user-configurable MRC pricing settings."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_settings(
        self,
        user_id: int,
        marketplace_account_id: int | None = None,
    ) -> MrcSettingsResult:
        """Get MRC settings for user, falling back to defaults."""
        query = select(MrcPricingSettings).where(
            MrcPricingSettings.user_id == user_id,
        )
        if marketplace_account_id is not None:
            query = query.where(MrcPricingSettings.marketplace_account_id == marketplace_account_id)
        else:
            query = query.where(MrcPricingSettings.marketplace_account_id.is_(None))

        result = await self.session.execute(query)
        settings = result.scalar_one_or_none()

        if settings is None:
            return MrcSettingsResult(
                default_discount_percent=DEFAULT_DISCOUNT_PERCENT,
                full_price_multiplier=DEFAULT_FULL_PRICE_MULTIPLIER,
                allowed_action_price_deviation_percent=DEFAULT_ALLOWED_DEVIATION_PERCENT,
                auto_promo_check_enabled=False,
                auto_add_to_promotions=False,
                auto_price_for_auto_promotions=False,
                is_default=True,
            )

        return MrcSettingsResult(
            default_discount_percent=settings.default_discount_percent,
            full_price_multiplier=settings.full_price_multiplier,
            allowed_action_price_deviation_percent=settings.allowed_action_price_deviation_percent,
            auto_promo_check_enabled=settings.auto_promo_check_enabled,
            auto_add_to_promotions=settings.auto_add_to_promotions,
            auto_price_for_auto_promotions=settings.auto_price_for_auto_promotions,
            is_default=False,
        )

    async def update_settings(
        self,
        user_id: int,
        *,
        default_discount_percent: Decimal | None = None,
        full_price_multiplier: Decimal | None = None,
        allowed_action_price_deviation_percent: Decimal | None = None,
        auto_promo_check_enabled: bool | None = None,
        auto_add_to_promotions: bool | None = None,
        auto_price_for_auto_promotions: bool | None = None,
        marketplace_account_id: int | None = None,
    ) -> MrcSettingsResult:
        """Update or create MRC settings for user."""
        query = select(MrcPricingSettings).where(
            MrcPricingSettings.user_id == user_id,
        )
        if marketplace_account_id is not None:
            query = query.where(MrcPricingSettings.marketplace_account_id == marketplace_account_id)
        else:
            query = query.where(MrcPricingSettings.marketplace_account_id.is_(None))

        result = await self.session.execute(query)
        settings = result.scalar_one_or_none()

        if settings is None:
            settings = MrcPricingSettings(
                user_id=user_id,
                marketplace_account_id=marketplace_account_id,
            )
            self.session.add(settings)

        if default_discount_percent is not None:
            settings.default_discount_percent = default_discount_percent
        if full_price_multiplier is not None:
            settings.full_price_multiplier = full_price_multiplier
        if allowed_action_price_deviation_percent is not None:
            settings.allowed_action_price_deviation_percent = allowed_action_price_deviation_percent
        if auto_promo_check_enabled is not None:
            settings.auto_promo_check_enabled = auto_promo_check_enabled
        if auto_add_to_promotions is not None:
            settings.auto_add_to_promotions = auto_add_to_promotions
        if auto_price_for_auto_promotions is not None:
            settings.auto_price_for_auto_promotions = auto_price_for_auto_promotions

        await self.session.flush()

        logger.info(
            "mrc_pricing_settings_updated",
            extra={
                "user_id": user_id,
                "marketplace_account_id": marketplace_account_id,
                "default_discount_percent": str(settings.default_discount_percent),
                "full_price_multiplier": str(settings.full_price_multiplier),
                "allowed_action_price_deviation_percent": str(
                    settings.allowed_action_price_deviation_percent
                ),
                "auto_promo_check_enabled": settings.auto_promo_check_enabled,
                "auto_add_to_promotions": settings.auto_add_to_promotions,
                "auto_price_for_auto_promotions": settings.auto_price_for_auto_promotions,
            },
        )

        return MrcSettingsResult(
            default_discount_percent=settings.default_discount_percent,
            full_price_multiplier=settings.full_price_multiplier,
            allowed_action_price_deviation_percent=settings.allowed_action_price_deviation_percent,
            auto_promo_check_enabled=settings.auto_promo_check_enabled,
            auto_add_to_promotions=settings.auto_add_to_promotions,
            auto_price_for_auto_promotions=settings.auto_price_for_auto_promotions,
            is_default=False,
        )

    @staticmethod
    def validate_settings(
        *,
        default_discount_percent: Decimal | None = None,
        full_price_multiplier: Decimal | None = None,
        allowed_action_price_deviation_percent: Decimal | None = None,
    ) -> list[str]:
        """Validate settings values. Returns list of error messages."""
        errors: list[str] = []

        if default_discount_percent is not None:
            if default_discount_percent < 0 or default_discount_percent > 99:
                errors.append("Процент скидки должен быть от 0 до 99")

        if full_price_multiplier is not None:
            if full_price_multiplier < 1 or full_price_multiplier > 20:
                errors.append("Коэффициент полной цены должен быть от 1 до 20")

        if allowed_action_price_deviation_percent is not None:
            if (
                allowed_action_price_deviation_percent < 0
                or allowed_action_price_deviation_percent > 100
            ):
                errors.append("Допустимое отклонение должно быть от 0 до 100")

        return errors
