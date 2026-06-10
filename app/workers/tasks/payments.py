"""version: 1.0.0
description: Worker tasks for payment reconciliation.
updated: 2026-06-10
"""

import logging
from typing import Any

from app.core.db import AsyncSessionFactory

logger = logging.getLogger(__name__)


async def reconcile_pending_payments(ctx: dict[str, Any], payload: dict | None = None) -> None:
    """Check PENDING YooKassa payments against the API and update status."""
    payload = payload or {}
    from app.services.payments.payment_service import PaymentService

    async with AsyncSessionFactory() as session:
        service = PaymentService(session)
        try:
            reconciled = await service.reconcile_pending_payments()
            await session.commit()
            if reconciled:
                logger.info(
                    "yookassa_reconciliation_completed",
                    extra={"reconciled_count": reconciled},
                )
        except Exception:
            logger.exception("yookassa_reconciliation_failed")
            try:
                await session.rollback()
            except Exception:
                pass


__all__ = [
    "reconcile_pending_payments",
]
