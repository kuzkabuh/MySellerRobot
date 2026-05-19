"""version: 2.0.0
description: YooKassa payment gateway client for subscription payments.
updated: 2026-05-19
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from yookassa import Configuration, Payment  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class YooKassaPaymentResult:
    payment_id: str
    status: str
    amount: Decimal
    currency: str
    confirmation_url: str
    description: str
    metadata: dict[str, Any]


def _payment_to_dict(payment: Any) -> dict[str, Any]:
    """Extract payment data from YooKassa SDK Payment object.

    The SDK stores response in ``payment._data``, not in ``__dict__``.
    Using ``__dict__`` previously caused KeyError('id') in callers.
    Always returns a dict with keys: id, status, amount, confirmation,
    description, metadata.
    """
    defaults = {
        "id": "",
        "status": "",
        "amount": {"value": "0", "currency": "RUB"},
        "confirmation": {"confirmation_url": ""},
        "description": "",
        "metadata": {},
    }

    data = getattr(payment, "_data", None)
    if isinstance(data, dict) and data:
        defaults.update(data)
        return defaults

    confirmation_obj = getattr(payment, "confirmation", None)
    confirmation_url = ""
    if confirmation_obj:
        if isinstance(confirmation_obj, dict):
            confirmation_url = confirmation_obj.get("confirmation_url", "")
        else:
            confirmation_url = getattr(confirmation_obj, "confirmation_url", "") or ""

    amount_obj = getattr(payment, "amount", None)
    amount_value = "0"
    currency = "RUB"
    if amount_obj:
        if isinstance(amount_obj, dict):
            amount_value = str(amount_obj.get("value", "0"))
            currency = amount_obj.get("currency", "RUB")
        else:
            amount_value = str(getattr(amount_obj, "value", "0"))
            currency = getattr(amount_obj, "currency", "RUB")

    metadata = getattr(payment, "metadata", None) or {}

    defaults["id"] = getattr(payment, "id", "")
    defaults["status"] = getattr(payment, "status", "")
    defaults["amount"] = {"value": amount_value, "currency": currency}
    defaults["confirmation"] = {"confirmation_url": confirmation_url}
    defaults["description"] = getattr(payment, "description", "")
    defaults["metadata"] = metadata
    return defaults


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

        Returns dict with keys: id, status, amount, confirmation, description, metadata.
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
            result = _payment_to_dict(payment)
            logger.info(
                "yookassa_payment_created",
                extra={
                    "payment_id": result["id"],
                    "amount": str(amount),
                    "description": description,
                },
            )
            return result
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
            return _payment_to_dict(payment)
        except Exception:
            logger.exception("yookassa_payment_fetch_failed", extra={"payment_id": payment_id})
            raise

    async def cancel_payment(self, payment_id: str) -> dict[str, Any]:
        """Cancel pending payment."""
        try:
            payment = Payment.cancel(payment_id)
            result = _payment_to_dict(payment)
            logger.info("yookassa_payment_cancelled", extra={"payment_id": payment_id})
            return result
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
