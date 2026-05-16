"""version: 1.0.0
description: Payment processing service with YooKassa integration.
updated: 2026-05-16
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.integrations.yookassa import YooKassaClient
from app.models.enums import PaymentStatus, SubscriptionStatus
from app.models.subscriptions import Payment, SubscriptionTier, UserSubscription
from app.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)


class PaymentService:
    """Handle payment creation and webhook processing."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        settings = get_settings()
        self.yookassa = YooKassaClient(
            shop_id=settings.yookassa_shop_id,
            secret_key=settings.yookassa_secret_key.get_secret_value(),
        )
        self.subscription_service = SubscriptionService(session)

    async def create_subscription_payment(
        self,
        *,
        user_id: int,
        tier_code: str,
        period: str = "monthly",
        return_url: str,
    ) -> tuple[Payment, str]:
        """Create payment for subscription.

        Returns (Payment, confirmation_url).
        """
        tier = await self._get_tier_by_code(tier_code)
        if not tier:
            raise ValueError(f"Tier {tier_code} not found")

        amount = tier.price_monthly if period == "monthly" else tier.price_yearly
        if amount is None or amount == Decimal("0"):
            raise ValueError(f"Tier {tier_code} has no price for {period} period")

        description = f"Подписка {tier.name} ({period})"
        metadata = {
            "user_id": str(user_id),
            "tier_code": tier_code,
            "period": period,
        }

        # Create payment in YooKassa
        yookassa_payment = await self.yookassa.create_payment(
            amount=amount,
            description=description,
            return_url=return_url,
            metadata=metadata,
        )

        # Save payment to database
        payment = Payment(
            user_id=user_id,
            provider="yookassa",
            provider_payment_id=yookassa_payment["id"],
            amount=amount,
            currency="RUB",
            status=PaymentStatus.PENDING,
            metadata=metadata,
        )
        self.session.add(payment)
        await self.session.flush()

        confirmation_url = yookassa_payment.get("confirmation", {}).get("confirmation_url", "")

        logger.info(
            "payment_created",
            extra={
                "payment_id": payment.id,
                "user_id": user_id,
                "tier_code": tier_code,
                "amount": str(amount),
            },
        )

        return payment, confirmation_url

    async def handle_payment_success(self, yookassa_data: dict[str, Any]) -> None:
        """Handle successful payment webhook from YooKassa."""
        payment_id = yookassa_data.get("id")
        if not payment_id:
            logger.error("yookassa_webhook_missing_payment_id")
            return

        # Find payment in database
        result = await self.session.execute(
            select(Payment).where(Payment.provider_payment_id == payment_id)
        )
        payment = result.scalar_one_or_none()
        if not payment:
            logger.error("payment_not_found", extra={"provider_payment_id": payment_id})
            return

        # Update payment status
        payment.status = PaymentStatus.SUCCEEDED
        payment.paid_at = datetime.now(tz=UTC)
        payment.payment_method = yookassa_data.get("payment_method", {}).get("type")

        # Extract metadata
        metadata = payment.metadata or {}
        tier_code = metadata.get("tier_code")
        period = metadata.get("period", "monthly")

        if not tier_code:
            logger.error("payment_missing_tier_code", extra={"payment_id": payment.id})
            await self.session.flush()
            return

        # Create or renew subscription
        active_subscription = await self.subscription_service.get_active_subscription(
            payment.user_id
        )

        if active_subscription:
            # Renew existing subscription
            subscription = await self.subscription_service.renew_subscription(
                active_subscription.id, payment_id=payment_id
            )
        else:
            # Create new subscription
            subscription = await self.subscription_service.create_subscription(
                user_id=payment.user_id,
                tier_code=tier_code,
                is_trial=False,
                payment_provider="yookassa",
                payment_id=payment_id,
            )

        payment.subscription_id = subscription.id
        await self.session.flush()

        logger.info(
            "payment_processed_successfully",
            extra={
                "payment_id": payment.id,
                "user_id": payment.user_id,
                "subscription_id": subscription.id,
            },
        )

    async def handle_payment_cancel(self, yookassa_data: dict[str, Any]) -> None:
        """Handle cancelled payment webhook from YooKassa."""
        payment_id = yookassa_data.get("id")
        if not payment_id:
            return

        result = await self.session.execute(
            select(Payment).where(Payment.provider_payment_id == payment_id)
        )
        payment = result.scalar_one_or_none()
        if not payment:
            return

        payment.status = PaymentStatus.CANCELLED
        await self.session.flush()

        logger.info("payment_cancelled", extra={"payment_id": payment.id})

    async def get_user_payments(self, user_id: int, limit: int = 10) -> list[Payment]:
        """Get user's payment history."""
        result = await self.session.execute(
            select(Payment)
            .where(Payment.user_id == user_id)
            .order_by(Payment.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def _get_tier_by_code(self, code: str) -> SubscriptionTier | None:
        """Get tier by code."""
        result = await self.session.execute(
            select(SubscriptionTier).where(SubscriptionTier.code == code)
        )
        return result.scalar_one_or_none()
