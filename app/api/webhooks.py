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


@router.post("/yookassa")
async def yookassa_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Handle YooKassa payment notifications.

    YooKassa sends notifications about payment status changes.
    """
    try:
        payload = await request.json()
        event_type = payload.get("event")
        payment_data = payload.get("object")

        if not event_type or not payment_data:
            logger.error("yookassa_webhook_invalid_payload", extra={"payload": payload})
            raise HTTPException(status_code=400, detail="Invalid payload")

        service = PaymentService(session)

        if event_type == "payment.succeeded":
            await service.handle_payment_success(payment_data)
            await session.commit()
        elif event_type == "payment.canceled":
            await service.handle_payment_cancel(payment_data)
            await session.commit()
        else:
            logger.info("yookassa_webhook_unhandled_event", extra={"event_type": event_type})

        return {"status": "ok"}

    except Exception:
        logger.exception("yookassa_webhook_processing_failed")
        await session.rollback()
        raise HTTPException(status_code=500, detail="Webhook processing failed")
