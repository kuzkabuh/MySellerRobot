"""version: 1.0.0
description: Webhook endpoints for payment providers.
updated: 2026-05-16
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.services.payment_service import PaymentService

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)
SESSION_DEPENDENCY = Depends(get_session)


@router.post("/yookassa")
async def yookassa_webhook(
    request: Request,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> dict[str, str]:
    """Handle YooKassa payment notifications.

    YooKassa sends notifications about payment status changes.
    """
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

    try:
        service = PaymentService(session)

        if event_type == "payment.succeeded":
            await service.handle_payment_success(payment_data)
            await session.commit()
            logger.info("yookassa_webhook_success_processed")
        elif event_type == "payment.canceled":
            await service.handle_payment_cancel(payment_data)
            await session.commit()
            logger.info("yookassa_webhook_cancel_processed")
        else:
            logger.info("yookassa_webhook_unhandled_event", extra={"event_type": event_type})

        return {"status": "ok"}

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("yookassa_webhook_processing_failed", extra={"error": str(exc)})
        await session.rollback()
        raise HTTPException(status_code=500, detail="Internal server error") from exc
