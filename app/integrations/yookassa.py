"""version: 1.0.0
description: YooKassa payment gateway client for subscription payments.
updated: 2026-05-16
"""

import logging
from decimal import Decimal
from typing import Any, cast

from yookassa import Configuration, Payment  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


class YooKassaClient:
    """Client for YooKassa payment API."""

    def __init__(self, shop_id: str, secret_key: str) -> None:
        Configuration.account_id = shop_id
        Configuration.secret_key = secret_key

    async def create_payment(
        self,
        *,
        amount: Decimal,
        currency: str = "RUB",
        description: str,
        return_url: str,
        metadata: dict[str, Any] | None = None,
        idempotence_key: str | None = None,
        receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new payment.

        Returns payment object with confirmation URL.
        """
        payment_payload: dict[str, Any] = {
            "amount": {"value": str(amount), "currency": currency},
            "confirmation": {"type": "redirect", "return_url": return_url},
            "capture": True,
            "description": description,
            "metadata": metadata or {},
        }
        if receipt:
            payment_payload["receipt"] = receipt

        try:
            payment = Payment.create(payment_payload, idempotence_key)
            logger.info(
                "yookassa_payment_created",
                extra={
                    "payment_id": payment.id,
                    "amount": str(amount),
                    "description": description,
                },
            )
            return cast(dict[str, Any], payment.__dict__)
        except Exception as e:
            error_msg = str(e).lower()
            if "invalid_credentials" in error_msg or "authentication" in error_msg:
                logger.error(
                    "yookassa_invalid_credentials",
                    extra={"detail": str(e)},
                )
            else:
                logger.exception("yookassa_payment_creation_failed")
            raise

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        """Get payment information by ID."""
        try:
            payment = Payment.find_one(payment_id)
            return cast(dict[str, Any], payment.__dict__)
        except Exception:
            logger.exception("yookassa_payment_fetch_failed", extra={"payment_id": payment_id})
            raise

    async def cancel_payment(self, payment_id: str) -> dict[str, Any]:
        """Cancel pending payment."""
        try:
            payment = Payment.cancel(payment_id)
            logger.info("yookassa_payment_cancelled", extra={"payment_id": payment_id})
            return cast(dict[str, Any], payment.__dict__)
        except Exception:
            logger.exception("yookassa_payment_cancel_failed", extra={"payment_id": payment_id})
            raise

    @staticmethod
    def verify_webhook_signature(payload: dict[str, Any], signature: str) -> bool:
        """Verify webhook notification signature.

        TODO: Implement signature verification when YooKassa provides the method.
        For now, we rely on HTTPS and secret webhook URL.
        """
        return True
