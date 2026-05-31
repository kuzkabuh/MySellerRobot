"""version: 5.1.0
description: Payment service with YooKassa webhooks, subscription periods, receipt generation,
    reconciliation, and post-payment notifications.
updated: 2026-05-21
"""

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from html import escape as html_escape
from inspect import isawaitable
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.integrations.yookassa import YooKassaClient
from app.models.domain import User
from app.models.enums import PaymentStatus
from app.models.subscriptions import Payment, SubscriptionTier
from app.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)

_PERIOD_LABELS = {
    "monthly": "1 месяц",
    "3_months": "3 месяца",
    "6_months": "6 месяцев",
    "yearly": "1 год",
}

_TIER_FEATURE_LABELS = [
    ("feature_web_cabinet", "Web-кабинет"),
    ("feature_analytics", "Расширенная аналитика"),
    ("feature_plan_fact", "План/факт анализ"),
    ("feature_break_even", "Безубыточная цена"),
    ("feature_stock_forecast", "Прогноз остатков"),
    ("feature_alerts", "Умные алерты"),
    ("feature_priority_support", "Приоритетная поддержка"),
    ("feature_api_access", "API-доступ"),
    ("feature_mrc_pricing", "МРЦ и акции WB"),
    ("feature_auto_promotions", "Автоакции WB"),
    ("feature_telegram_notifications", "Telegram-уведомления"),
]


def _get_tier_price_for_period(tier: SubscriptionTier, period: str) -> Decimal | None:
    price_map = {
        "monthly": tier.price_monthly,
        "3_months": tier.price_3_months,
        "6_months": tier.price_6_months,
        "yearly": tier.price_yearly,
    }
    return price_map.get(period)


def _build_receipt(
    *,
    tier_name: str,
    period: str,
    amount: Decimal,
    customer_email: str,
) -> dict[str, Any]:
    """Build YooKassa-compliant receipt for a subscription payment."""
    period_label = _PERIOD_LABELS.get(period, period)
    item_description = f"Подписка MP Control — тариф {tier_name}, {period_label}"
    return {
        "customer": {"email": customer_email},
        "items": [
            {
                "description": item_description,
                "quantity": "1.00",
                "amount": {"value": str(amount), "currency": "RUB"},
                "vat_code": 1,
                "payment_subject": "service",
                "payment_mode": "full_payment",
            }
        ],
    }


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
            raise RuntimeError("Платёжная система не настроена. Обратитесь к администратору.")

    def _generate_idempotence_key(self, *, user_id: int, tier_code: str, period: str) -> str:
        """Generate a unique YooKassa idempotence key."""
        return uuid.uuid4().hex

    async def create_subscription_payment(
        self,
        *,
        user_id: int,
        tier_code: str,
        period: str = "monthly",
        return_url: str,
        customer_email: str,
        promo_code_usage_id: int | None = None,
        discount_amount: Decimal | None = None,
        original_amount: Decimal | None = None,
    ) -> tuple[Payment, str]:
        """Create payment for subscription.

        Returns (Payment, confirmation_url).

        If a PENDING payment already exists for this user, returns it
        instead of creating a duplicate.
        """
        tier = await self._get_tier_by_code(tier_code)
        if not tier:
            raise ValueError(f"Tier {tier_code} not found")

        amount = _get_tier_price_for_period(tier, period)
        if amount is None or amount == Decimal("0"):
            raise ValueError(f"Tier {tier_code} has no price for {period} period")

        if discount_amount is not None and discount_amount > 0:
            final_amount = max(amount - discount_amount, Decimal("0.01"))
        else:
            final_amount = amount

        existing = None
        if promo_code_usage_id is None and not discount_amount:
            existing = await self._find_pending_payment(
                user_id, tier_code=tier_code, period=period
            )
        if existing:
            logger.info(
                "payment_reused_pending",
                extra={
                    "payment_id": existing.id,
                    "user_id": user_id,
                    "tier_code": tier_code,
                },
            )
            meta = existing.payment_metadata or {}
            confirmation_url = meta.get("confirmation_url", "")
            if not confirmation_url:
                confirmation_url = (
                    await self._get_confirmation_url(existing.provider_payment_id) or ""
                )
                if confirmation_url:
                    meta["confirmation_url"] = confirmation_url
                    existing.payment_metadata = meta
                    await self.session.flush()
            return existing, confirmation_url

        period_label = _PERIOD_LABELS.get(period, period)
        description = f"Подписка MP Control — тариф {tier.name}, {period_label}"
        metadata: dict[str, Any] = {
            "user_id": str(user_id),
            "tier_code": tier_code,
            "period": period,
            "provider": "yookassa",
        }
        if promo_code_usage_id is not None:
            metadata["promo_code_usage_id"] = str(promo_code_usage_id)
        if discount_amount is not None and discount_amount > 0:
            metadata["discount_amount"] = str(discount_amount)
        if original_amount is not None:
            metadata["original_amount"] = str(original_amount)
        metadata["final_amount"] = str(final_amount)

        idempotence_key = self._generate_idempotence_key(
            user_id=user_id, tier_code=tier_code, period=period
        )

        receipt = _build_receipt(
            tier_name=tier.name,
            period=period,
            amount=final_amount,
            customer_email=customer_email,
        )

        self._check_credentials()

        logger.info(
            "yookassa_payment_request",
            extra={
                "user_id": user_id,
                "tier_code": tier_code,
                "period": period,
                "amount": str(final_amount),
                "discount_amount": str(discount_amount) if discount_amount else None,
                "customer_email_present": bool(customer_email),
                "receipt_items_count": len(receipt.get("items", [])),
            },
        )

        # Create payment in YooKassa
        yookassa_payment = await self.yookassa.create_payment(
            amount=final_amount,
            description=description,
            return_url=return_url,
            metadata=metadata,
            idempotence_key=idempotence_key,
            receipt=receipt,
        )

        # Save payment to database
        payment = Payment(
            user_id=user_id,
            provider="yookassa",
            provider_payment_id=yookassa_payment["id"],
            amount=final_amount,
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={
                **metadata,
                "idempotence_key": idempotence_key,
                "confirmation_url": (
                    yookassa_payment.get("confirmation", {}).get("confirmation_url", "")
                ),
            },
        )
        self.session.add(payment)
        await self.session.flush()

        payment_metadata = payment.payment_metadata or {}
        confirmation_url = str(payment_metadata.get("confirmation_url", ""))

        logger.info(
            "payment_created",
            extra={
                "payment_id": payment.id,
                "user_id": user_id,
                "tier_code": tier_code,
                "amount": str(final_amount),
                "discount_amount": str(discount_amount) if discount_amount else None,
            },
        )

        return payment, confirmation_url

    async def handle_payment_success(self, yookassa_data: dict[str, Any]) -> None:
        """Handle successful payment webhook from YooKassa.

        Delegates to _confirm_payment for the core business logic.
        """
        payment_id = yookassa_data.get("id")
        if not payment_id:
            logger.error("payment_success_missing_id")
            return

        logger.info(
            "yookassa_webhook_received",
            extra={"event": "payment.succeeded", "provider_payment_id": payment_id},
        )

        await self._confirm_payment(payment_id, yookassa_data, source="webhook")

    async def handle_payment_cancel(self, yookassa_data: dict[str, Any]) -> None:
        """Handle cancelled payment webhook from YooKassa.

        Idempotent: repeated calls are safely ignored.
        Secure: does not cancel already succeeded payments.
        """
        payment_id = yookassa_data.get("id")
        if not payment_id:
            logger.error("payment_cancel_missing_id")
            return

        logger.info(
            "yookassa_webhook_received",
            extra={"event": "payment.canceled", "provider_payment_id": payment_id},
        )

        result = await self.session.execute(
            select(Payment).where(Payment.provider_payment_id == payment_id)
        )
        payment = result.scalar_one_or_none()
        if not payment:
            logger.warning(
                "yookassa_webhook_unknown_payment",
                extra={"provider_payment_id": payment_id},
            )
            return

        if payment.status == PaymentStatus.SUCCEEDED:
            logger.warning(
                "payment_cancel_ignored_already_succeeded",
                extra={"payment_id": payment.id, "provider_payment_id": payment_id},
            )
            return

        if payment.status == PaymentStatus.CANCELLED:
            logger.info(
                "payment_cancel_duplicate_ignored",
                extra={"payment_id": payment.id, "provider_payment_id": payment_id},
            )
            return

        try:
            verified_payment = await self.yookassa.get_payment(payment_id)
            verified_status = verified_payment.get("status")

            if verified_status not in {"canceled", "cancelled"}:
                logger.warning(
                    "yookassa_webhook_status_mismatch",
                    extra={
                        "payment_id": payment.id,
                        "webhook_event": "payment.canceled",
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

        try:
            from app.services.promo_code_service import PromoCodeService

            promo_service = PromoCodeService(self.session)
            await promo_service.cancel_usage_by_payment(payment_id)
        except Exception:
            logger.exception(
                "promo_code_cancel_failed",
                extra={"provider_payment_id": payment_id},
            )

        logger.info(
            "payment_status_updated",
            extra={
                "payment_id": payment.id,
                "user_id": payment.user_id,
                "old_status": "PENDING",
                "new_status": "CANCELLED",
            },
        )

    async def confirm_payment(
        self,
        provider_payment_id: str,
        *,
        yookassa_data: dict[str, Any] | None = None,
        source: str = "return_page",
    ) -> Payment | None:
        """Public entry point for payment confirmation.

        Used by webhook, reconciliation, and return page reconciliation.
        Returns the Payment object if found and processed, None otherwise.
        """
        await self._confirm_payment(
            provider_payment_id,
            yookassa_data=yookassa_data,
            source=source,
        )

        result = await self.session.execute(
            select(Payment).where(Payment.provider_payment_id == provider_payment_id)
        )
        return result.scalar_one_or_none()

    async def _confirm_payment(
        self,
        payment_id: str,
        yookassa_data: dict[str, Any] | None = None,
        *,
        source: str = "webhook",
    ) -> None:
        """Core payment confirmation logic shared by webhook and reconciliation.

        1. Find local Payment by provider_payment_id.
        2. Verify status via YooKassa API.
        3. Activate subscription.
        4. Update payment status.
        5. Notify user via Telegram.
        """
        logger.info(
            "subscription_payment_confirmation_started",
            extra={"provider_payment_id": payment_id, "source": source},
        )

        result = await self.session.execute(
            select(Payment).where(Payment.provider_payment_id == payment_id)
        )
        payment = result.scalar_one_or_none()
        if not payment:
            logger.warning(
                "yookassa_webhook_unknown_payment",
                extra={"provider_payment_id": payment_id, "source": source},
            )
            return

        if payment.status == PaymentStatus.SUCCEEDED:
            logger.info(
                "subscription_activation_skipped_already_processed",
                extra={"payment_id": payment.id, "provider_payment_id": payment_id},
            )
            return

        if payment.status == PaymentStatus.CANCELLED:
            logger.info(
                "payment_confirmation_skipped_cancelled",
                extra={"payment_id": payment.id, "provider_payment_id": payment_id},
            )
            return

        try:
            provider_payment = await self.yookassa.get_payment(payment_id)
        except Exception as e:
            logger.exception(
                "payment_verification_error",
                extra={"payment_id": payment.id, "error": str(e), "source": source},
            )
            return

        webhook_payment_method = (yookassa_data or {}).get("payment_method")
        yookassa_data = {
            **(yookassa_data or {}),
            **provider_payment,
        }
        if webhook_payment_method and "payment_method" not in yookassa_data:
            yookassa_data["payment_method"] = webhook_payment_method

        verified_status = yookassa_data.get("status")
        if verified_status != "succeeded":
            logger.warning(
                "yookassa_webhook_status_mismatch",
                extra={
                    "payment_id": payment.id,
                    "verified_status": verified_status,
                    "source": source,
                },
            )
            return

        logger.info(
            "subscription_payment_status_verified",
            extra={
                "payment_id": payment.id,
                "provider_payment_id": payment_id,
                "user_id": payment.user_id,
            },
        )

        metadata = payment.payment_metadata or {}
        tier_code = metadata.get("tier_code")
        period = metadata.get("period") or metadata.get("subscription_period")
        user_id = metadata.get("user_id")

        if not tier_code:
            logger.error(
                "paid_payment_unknown_tier_or_period",
                extra={
                    "payment_id": payment.id,
                    "provider_payment_id": payment_id,
                    "user_id": payment.user_id,
                    "metadata": metadata,
                    "detail": "tier_code missing from payment metadata",
                },
            )
            payment.status = PaymentStatus.SUCCEEDED
            payment.paid_at = datetime.now(tz=UTC)
            await self.session.flush()
            return

        if not period:
            period = "monthly"
            logger.warning(
                "paid_payment_period_missing_defaulted",
                extra={
                    "payment_id": payment.id,
                    "provider_payment_id": payment_id,
                    "user_id": payment.user_id,
                    "default_period": period,
                },
            )

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

        logger.info(
            "subscription_payment_matched_by_provider_id",
            extra={
                "payment_id": payment.id,
                "provider_payment_id": payment_id,
                "user_id": payment.user_id,
                "tier_code": tier_code,
                "period": period,
            },
        )

        logger.info(
            "subscription_activation_started",
            extra={
                "payment_id": payment.id,
                "user_id": payment.user_id,
                "tier_code": tier_code,
                "period": period,
            },
        )

        subscription = None
        try:
            subscription = await self.subscription_service.create_subscription(
                user_id=payment.user_id,
                tier_code=tier_code,
                period=period,
                is_trial=False,
                payment_provider="yookassa",
                payment_id=payment.provider_payment_id,
            )
            payment.subscription_id = subscription.id
        except ValueError as exc:
            logger.error(
                "subscription_activation_failed",
                extra={
                    "payment_id": payment.id,
                    "user_id": payment.user_id,
                    "tier_code": tier_code,
                    "period": period,
                    "error": str(exc),
                },
            )

        payment.status = PaymentStatus.SUCCEEDED
        payment.paid_at = datetime.now(tz=UTC)
        payment.payment_method = yookassa_data.get("payment_method", {}).get("type")
        await self.session.flush()

        promo_usage_id = metadata.get("promo_code_usage_id")
        if promo_usage_id:
            try:
                from app.services.promo_code_service import PromoCodeService

                promo_service = PromoCodeService(self.session)
                await promo_service.confirm_usage(
                    usage_id=int(promo_usage_id),
                    payment_id=payment.id,
                    subscription_id=subscription.id if subscription else None,
                    provider_payment_id=payment.provider_payment_id,
                )
            except Exception:
                logger.exception(
                    "promo_code_confirm_failed",
                    extra={
                        "payment_id": payment.id,
                        "promo_usage_id": promo_usage_id,
                    },
                )

        logger.info(
            "subscription_payment_marked_paid",
            extra={
                "payment_id": payment.id,
                "user_id": payment.user_id,
                "tier_code": tier_code,
                "period": period,
                "subscription_id": subscription.id if subscription else None,
            },
        )

        if subscription:
            logger.info(
                "subscription_activated_from_payment",
                extra={
                    "payment_id": payment.id,
                    "user_id": payment.user_id,
                    "subscription_id": subscription.id,
                    "tier_code": tier_code,
                    "period": period,
                    "expires_at": (
                        subscription.expires_at.isoformat() if subscription.expires_at else None
                    ),
                },
            )

            await self._save_receipt_info(payment, yookassa_data)
            await self._send_payment_success_notification(
                payment=payment,
                subscription=subscription,
                tier_code=tier_code,
                period=period,
            )
        elif source == "reconciliation":
            logger.info(
                "reconciled_paid_payment_processed",
                extra={
                    "payment_id": payment.id,
                    "user_id": payment.user_id,
                    "tier_code": tier_code,
                    "period": period,
                    "subscription_created": False,
                },
            )

    async def _save_receipt_info(
        self,
        payment: Payment,
        yookassa_data: dict[str, Any],
    ) -> None:
        """Extract and save receipt information from YooKassa payment response."""
        receipt_data = yookassa_data.get("receipt")
        if not receipt_data:
            return

        receipt_id = receipt_data.get("id") or receipt_data.get("receipt_id")
        receipt_status = receipt_data.get("status") or receipt_data.get("registration_status")

        if receipt_id:
            payment.receipt_id = receipt_id
        if receipt_status:
            payment.receipt_status = receipt_status

        logger.info(
            "payment_receipt_info_saved",
            extra={
                "payment_id": payment.id,
                "receipt_id": receipt_id,
                "receipt_status": receipt_status,
            },
        )

    async def _fetch_receipt_status(self, payment: Payment) -> str | None:
        """Fetch current receipt status from YooKassa API if receipt_id is known."""
        if not payment.receipt_id:
            return None
        try:
            yk_data = await self.yookassa.get_payment(payment.provider_payment_id)
            receipt_data = yk_data.get("receipt")
            if isinstance(receipt_data, dict):
                status = receipt_data.get("status") or receipt_data.get("registration_status")
                if isinstance(status, str) and status:
                    payment.receipt_status = status
                    await self.session.flush()
                    return status
        except Exception as e:
            logger.warning(
                "payment_receipt_status_fetch_failed",
                extra={
                    "payment_id": payment.id,
                    "receipt_id": payment.receipt_id,
                    "error": str(e),
                },
            )
        return payment.receipt_status if isinstance(payment.receipt_status, str) else None

    async def _send_payment_success_notification(
        self,
        *,
        payment: Payment,
        subscription: Any,
        tier_code: str,
        period: str,
    ) -> None:
        """Send Telegram notification about successful payment and subscription activation.

        Idempotent: checks success_notification_sent_at to avoid duplicates.
        """
        from app.bot.main import create_bot
        from app.utils.datetime import format_datetime_for_user

        if payment.success_notification_sent_at is not None:
            logger.info(
                "payment_success_notification_skipped_duplicate",
                extra={
                    "payment_id": payment.id,
                    "user_id": payment.user_id,
                    "yookassa_payment_id": payment.provider_payment_id,
                },
            )
            return

        try:
            user_result = await self.session.execute(select(User).where(User.id == payment.user_id))
            user = user_result.scalar_one_or_none()
            if not user or not user.telegram_id:
                logger.warning(
                    "payment_success_notification_failed",
                    extra={
                        "payment_id": payment.id,
                        "user_id": payment.user_id,
                        "error": "user_not_found_or_no_telegram_id",
                    },
                )
                return

            tier = await self._get_tier_by_code(tier_code)
            tier_name = tier.name if tier else tier_code
            period_label = _PERIOD_LABELS.get(period, period)

            expires_str = "н/д"
            if subscription.expires_at:
                expires_str = format_datetime_for_user(
                    subscription.expires_at, user.timezone, "%d.%m.%Y"
                )

            paid_at_str = "н/д"
            if payment.paid_at:
                paid_at_str = format_datetime_for_user(
                    payment.paid_at, user.timezone, "%d.%m.%Y %H:%M"
                )

            features = []
            if tier:
                for attr, label in _TIER_FEATURE_LABELS:
                    if getattr(tier, attr, False):
                        features.append(label)

            feature_lines = ""
            if features:
                feature_items = "\n".join(f"✅ {f}" for f in features)
                feature_lines = f"\n{feature_items}"

            text = (
                f"✅ <b>Оплата получена</b>\n\n"
                f"Ваш платёж успешно подтверждён.\n"
                f"Подписка MP Control активирована.\n\n"
                f"💳 <b>Детали платежа</b>\n"
                f"• Тариф: {html_escape(tier_name)}\n"
                f"• Период: {html_escape(period_label)}\n"
                f"• Сумма: {payment.amount} ₽\n"
                f"• Статус: Оплачено\n"
                f"• Дата оплаты: {html_escape(paid_at_str)}\n\n"
                f"🚀 <b>Ваша подписка</b>\n"
                f"• Тариф: {html_escape(tier_name)}\n"
                f"• Статус: Активна\n"
                f"• Действует до: {html_escape(expires_str)}\n\n"
                f"Доступ открыт:{feature_lines}\n\n"
                f"Спасибо за оплату! Подписка уже работает."
            )

            keyboard = self._build_payment_success_keyboard(payment.id)

            bot = create_bot()
            try:
                await bot.send_message(
                    user.telegram_id,
                    text,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
            finally:
                close_result = bot.session.close()
                if isawaitable(close_result):
                    await close_result

            payment.success_notification_sent_at = datetime.now(tz=UTC)
            await self.session.flush()

            logger.info(
                "payment_success_notification_sent",
                extra={
                    "payment_id": payment.id,
                    "user_id": payment.user_id,
                    "telegram_id": user.telegram_id,
                    "yookassa_payment_id": payment.provider_payment_id,
                },
            )
        except Exception:
            logger.exception(
                "payment_success_notification_failed",
                extra={
                    "payment_id": payment.id,
                    "user_id": payment.user_id,
                    "yookassa_payment_id": payment.provider_payment_id,
                },
            )

    def _build_payment_success_keyboard(self, payment_id: int) -> Any:
        """Build inline keyboard for payment success message."""
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💳 Моя подписка",
                        callback_data="subscription:current",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🧾 Чек по платежу",
                        callback_data=f"subscription:receipt:{payment_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🏠 Главное меню",
                        callback_data="back_main",
                    )
                ],
            ]
        )

    async def _notify_user_subscription_activated(
        self,
        *,
        user_id: int,
        tier_code: str,
        period: str,
        expires_at: datetime | None,
    ) -> None:
        """Legacy notification method. Kept for backward compatibility.

        New code should use _send_payment_success_notification instead.
        """
        from app.bot.bot_provider import bot_session
        from app.utils.datetime import format_datetime_for_user

        try:
            tier = await self._get_tier_by_code(tier_code)
            tier_name = tier.name if tier else tier_code
            period_label = _PERIOD_LABELS.get(period, period)

            user_result = await self.session.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            if not user or not user.telegram_id:
                return

            expires_str = "н/д"
            if expires_at:
                expires_str = format_datetime_for_user(expires_at, user.timezone, "%d.%m.%Y")

            text = (
                f"✅ Оплата получена\n\n"
                f"Подписка MP Control — тариф {tier_name}, {period_label} активирована.\n"
                f"Действует до: {expires_str}"
            )

            async with bot_session() as bot:
                await bot.send_message(user.telegram_id, text, parse_mode="HTML")
            logger.info(
                "subscription_notification_sent",
                extra={"user_id": user_id, "telegram_id": user.telegram_id},
            )
        except Exception:
            logger.exception(
                "subscription_notification_failed",
                extra={"user_id": user_id},
            )

    async def reconcile_pending_payments(self) -> int:
        """Check all PENDING payments against YooKassa API and update status.

        Returns the number of payments reconciled.
        """
        result = await self.session.execute(
            select(Payment).where(
                Payment.status == PaymentStatus.PENDING,
                Payment.provider == "yookassa",
            )
        )
        pending = list(result.scalars().all())
        reconciled = 0

        for payment in pending:
            if payment.status != PaymentStatus.PENDING:
                continue

            try:
                yk_data = await self.yookassa.get_payment(payment.provider_payment_id)
                status = yk_data.get("status")

                if status == "succeeded":
                    await self._confirm_payment(
                        payment.provider_payment_id,
                        yookassa_data=yk_data,
                        source="reconciliation",
                    )
                    reconciled += 1
                elif status in {"canceled", "cancelled"}:
                    payment.status = PaymentStatus.CANCELLED
                    await self.session.flush()
                    reconciled += 1
                    logger.info(
                        "yookassa_pending_payment_reconciled",
                        extra={
                            "payment_id": payment.id,
                            "provider_payment_id": payment.provider_payment_id,
                            "new_status": "CANCELLED",
                        },
                    )
            except Exception:
                logger.exception(
                    "yookassa_reconciliation_payment_check_failed",
                    extra={
                        "payment_id": payment.id,
                        "provider_payment_id": payment.provider_payment_id,
                    },
                )

        return reconciled

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

    async def _find_pending_payment(
        self, user_id: int, *, tier_code: str, period: str
    ) -> Payment | None:
        """Return the most recent PENDING payment for a user+tier+period, if any.

        Matches payments where metadata period equals the requested period,
        checking both ``period`` and ``subscription_period`` keys for backward
        compatibility with older payment records.
        """
        result = await self.session.execute(
            select(Payment)
            .where(
                Payment.user_id == user_id,
                Payment.status == PaymentStatus.PENDING,
                text("payment_metadata->>'tier_code' = :tier_code").bindparams(tier_code=tier_code),
                text(
                    "(payment_metadata->>'period' = :period"
                    " OR payment_metadata->>'subscription_period' = :period)"
                ).bindparams(period=period),
            )
            .order_by(Payment.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_confirmation_url(self, provider_payment_id: str) -> str | None:
        """Fetch confirmation URL from YooKassa for an existing payment."""
        try:
            payment_data = await self.yookassa.get_payment(provider_payment_id)
            confirmation = payment_data.get("confirmation")
            if isinstance(confirmation, dict):
                confirmation_url = confirmation.get("confirmation_url")
                if isinstance(confirmation_url, str):
                    return confirmation_url
            return None
        except Exception:
            logger.warning(
                "payment_confirmation_url_fetch_failed",
                extra={"provider_payment_id": provider_payment_id},
            )
            return None
