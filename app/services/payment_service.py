"""version: 2.1.0
description: Payment service with secure YooKassa webhooks and subscription periods.
updated: 2026-05-17
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.integrations.yookassa import YooKassaClient
from app.models.enums import PaymentStatus
from app.models.subscriptions import Payment, SubscriptionTier
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
        self._credentials_valid = bool(
            settings.yookassa_shop_id and settings.yookassa_secret_key.get_secret_value()
        )

    def _check_credentials(self) -> None:
        if not self._credentials_valid:
            logger.error(
                "yookassa_invalid_credentials",
                extra={"detail": "shop_id or secret_key is empty"},
            )
            raise RuntimeError(
                "Платёжная система не настроена. Обратитесь к администратору."
            )

    def _generate_idempotence_key(
        self, *, user_id: int, tier_code: str, period: str
    ) -> str:
        return str(uuid4())

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
            "subscription_period": period,
            "period": period,
            "provider": "yookassa",
        }
        idempotence_key = self._generate_idempotence_key(
            user_id=user_id, tier_code=tier_code, period=period
        )

        self._check_credentials()

        # Create payment in YooKassa
        yookassa_payment = await self.yookassa.create_payment(
            amount=amount,
            description=description,
            return_url=return_url,
            metadata=metadata,
            idempotence_key=idempotence_key,
        )

        # Save payment to database
        payment = Payment(
            user_id=user_id,
            provider="yookassa",
            provider_payment_id=yookassa_payment["id"],
            amount=amount,
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={**metadata, "idempotence_key": idempotence_key},
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
        """Handle successful payment webhook from YooKassa.

        Idempotent: repeated calls with same payment_id are safely ignored.
        Secure: verifies payment status with YooKassa API before processing.
        """
        payment_id = yookassa_data.get("id")
        if not payment_id:
            logger.error("payment_success_missing_id")
            return

        logger.info("payment_success_received", extra={"provider_payment_id": payment_id})

        # Find payment in database
        result = await self.session.execute(
            select(Payment).where(Payment.provider_payment_id == payment_id)
        )
        payment = result.scalar_one_or_none()
        if not payment:
            logger.error("payment_not_found", extra={"provider_payment_id": payment_id})
            return

        # Idempotency: if already succeeded, ignore duplicate webhook
        if payment.status == PaymentStatus.SUCCEEDED:
            logger.info(
                "payment_success_duplicate_ignored",
                extra={"payment_id": payment.id, "provider_payment_id": payment_id},
            )
            return

        # Security: verify payment status with YooKassa API
        try:
            verified_payment = await self.yookassa.get_payment(payment_id)
            verified_status = verified_payment.get("status")

            if verified_status != "succeeded":
                logger.warning(
                    "payment_success_verification_failed",
                    extra={
                        "payment_id": payment.id,
                        "webhook_status": "succeeded",
                        "verified_status": verified_status,
                    },
                )
                return

            logger.info(
                "payment_success_verified",
                extra={"payment_id": payment.id, "provider_payment_id": payment_id},
            )
        except Exception as e:
            logger.exception(
                "payment_verification_error",
                extra={"payment_id": payment.id, "error": str(e)},
            )
            return

        # Validate metadata
        metadata = payment.payment_metadata or {}
        tier_code = metadata.get("tier_code")
        period = metadata.get("subscription_period") or metadata.get("period", "monthly")
        user_id = metadata.get("user_id")

        if not tier_code:
            logger.error(
                "payment_missing_tier_code",
                extra={"payment_id": payment.id, "metadata": metadata},
            )
            return

        if not user_id or str(payment.user_id) != str(user_id):
            logger.error(
                "payment_user_id_mismatch",
                extra={
                    "payment_id": payment.id,
                    "payment_user_id": payment.user_id,
                    "metadata_user_id": user_id,
                },
            )
            return

        try:
            subscription = await self.subscription_service.create_subscription(
                user_id=payment.user_id,
                tier_code=tier_code,
                period=period,
                is_trial=False,
                payment_provider="yookassa",
                payment_id=payment.provider_payment_id,
            )
        except ValueError as exc:
            logger.error(
                "payment_subscription_activation_failed",
                extra={"payment_id": payment.id, "error": str(exc)},
            )
            return

        payment.status = PaymentStatus.SUCCEEDED
        payment.paid_at = datetime.now(tz=UTC)
        payment.payment_method = yookassa_data.get("payment_method", {}).get("type")
        payment.subscription_id = subscription.id
        await self.session.flush()

        logger.info(
            "payment_processed_successfully",
            extra={
                "payment_id": payment.id,
                "user_id": payment.user_id,
                "subscription_id": subscription.id,
                "tier_code": tier_code,
                "period": period,
            },
        )

    async def handle_payment_cancel(self, yookassa_data: dict[str, Any]) -> None:
        """Handle cancelled payment webhook from YooKassa.

        Idempotent: repeated calls are safely ignored.
        Secure: does not cancel already succeeded payments.
        """
        payment_id = yookassa_data.get("id")
        if not payment_id:
            logger.error("payment_cancel_missing_id")
            return

        logger.info("payment_cancel_received", extra={"provider_payment_id": payment_id})

        result = await self.session.execute(
            select(Payment).where(Payment.provider_payment_id == payment_id)
        )
        payment = result.scalar_one_or_none()
        if not payment:
            logger.warning("payment_cancel_not_found", extra={"provider_payment_id": payment_id})
            return

        # Security: do not cancel already succeeded payments
        if payment.status == PaymentStatus.SUCCEEDED:
            logger.warning(
                "payment_cancel_ignored_already_succeeded",
                extra={"payment_id": payment.id, "provider_payment_id": payment_id},
            )
            return

        # Idempotency: if already cancelled, ignore duplicate webhook
        if payment.status == PaymentStatus.CANCELLED:
            logger.info(
                "payment_cancel_duplicate_ignored",
                extra={"payment_id": payment.id, "provider_payment_id": payment_id},
            )
            return

        # Verify with YooKassa API
        try:
            verified_payment = await self.yookassa.get_payment(payment_id)
            verified_status = verified_payment.get("status")

            if verified_status not in {"canceled", "cancelled"}:
                logger.warning(
                    "payment_cancel_verification_failed",
                    extra={
                        "payment_id": payment.id,
                        "webhook_status": "canceled",
                        "verified_status": verified_status,
                    },
                )
                return

            logger.info(
                "payment_cancel_verified",
                extra={"payment_id": payment.id, "provider_payment_id": payment_id},
            )
        except Exception as e:
            logger.exception(
                "payment_cancel_verification_error",
                extra={"payment_id": payment.id, "error": str(e)},
            )
            return

        payment.status = PaymentStatus.CANCELLED
        await self.session.flush()

        logger.info(
            "payment_cancelled",
            extra={"payment_id": payment.id, "user_id": payment.user_id},
        )

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
