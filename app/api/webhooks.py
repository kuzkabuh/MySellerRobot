"""version: 2.0.0
description: Webhook endpoints for payment providers with structured logging.
updated: 2026-05-19
"""

import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.services.payment_service import PaymentService

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)
SESSION_DEPENDENCY = Depends(get_session)
YOOKASSA_WEBHOOK_SECRET_HEADER = "x-yookassa-webhook-secret"


def _verify_yookassa_webhook_secret(request: Request) -> None:
    settings = get_settings()
    expected_secret = settings.get_yookassa_webhook_secret()
    if not expected_secret:
        if settings.webhook_insecure_dev_allowed:
            logger.warning("yookassa_webhook_insecure_dev_mode")
            return
        logger.error("yookassa_webhook_secret_not_configured")
        raise HTTPException(status_code=403, detail="Webhook secret is not configured")

    provided_secret = request.headers.get(YOOKASSA_WEBHOOK_SECRET_HEADER) or ""
    if not hmac.compare_digest(provided_secret, expected_secret):
        logger.warning(
            "yookassa_webhook_invalid_secret",
            extra={"provided": bool(provided_secret)},
        )
        raise HTTPException(status_code=403, detail="Invalid webhook secret")


@router.post("/yookassa")
async def yookassa_webhook(
    request: Request,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> dict[str, str]:
    """Handle YooKassa payment notifications.

    YooKassa sends POST requests with JSON payload:
    {
        "type": "notification",
        "event": "payment.succeeded",
        "object": {
            "id": "payment-id",
            "status": "succeeded",
            "paid": true,
            ...
        }
    }

    Supported events: payment.succeeded, payment.canceled
    """
    _verify_yookassa_webhook_secret(request)

    try:
        payload = await request.json()
    except Exception as exc:
        logger.error("yookassa_webhook_invalid_json", extra={"error": str(exc)})
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    event_type = payload.get("event")
    payment_data = payload.get("object")

    if not event_type or not payment_data:
        logger.error(
            "yookassa_webhook_missing_fields",
            extra={"has_event": bool(event_type), "has_object": bool(payment_data)},
        )
        raise HTTPException(status_code=400, detail="Missing required fields")

    payment_id = payment_data.get("id", "unknown")
    logger.info(
        "yookassa_webhook_received",
        extra={
            "event": event_type,
            "provider_payment_id": payment_id,
            "paid": payment_data.get("paid"),
        },
    )

    try:
        service = PaymentService(session)

        if event_type == "payment.succeeded":
            await service.handle_payment_success(payment_data)
            await session.commit()
            logger.info(
                "yookassa_webhook_success_processed",
                extra={"provider_payment_id": payment_id},
            )
        elif event_type == "payment.canceled":
            await service.handle_payment_cancel(payment_data)
            await session.commit()
            logger.info(
                "yookassa_webhook_cancel_processed",
                extra={"provider_payment_id": payment_id},
            )
        else:
            logger.info(
                "yookassa_webhook_unhandled_event",
                extra={"event_type": event_type},
            )

        return {"status": "ok"}

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "yookassa_webhook_processing_failed",
            extra={"error": str(exc), "event": event_type, "provider_payment_id": payment_id},
        )
        await session.rollback()
        raise HTTPException(status_code=500, detail="Internal server error") from exc
