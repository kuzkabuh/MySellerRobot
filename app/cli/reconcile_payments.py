"""version: 1.0.0
description: One-time CLI command to reconcile stuck PENDING payments with YooKassa.
updated: 2026-05-19

Usage:
    python -m app.cli.reconcile_payments
"""

import asyncio
import logging

from app.core.db import AsyncSessionFactory
from app.services.payment_service import PaymentService

logger = logging.getLogger(__name__)


async def _run() -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info("yookassa_pending_reconciliation_started")

    async with AsyncSessionFactory() as session:
        service = PaymentService(session)
        try:
            reconciled = await service.reconcile_pending_payments()
            await session.commit()
            logger.info(
                "yookassa_pending_reconciliation_completed",
                extra={"reconciled_count": reconciled},
            )
        except Exception:
            logger.exception("yookassa_reconciliation_failed")
            await session.rollback()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
