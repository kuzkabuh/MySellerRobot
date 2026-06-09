"""version: 1.1.0
description: Compatibility facade. Moved to app.services.payments.payment_service.
updated: 2026-06-09
"""

from app.services.payments.payment_service import (  # noqa: F401
    PaymentService,
)

__all__ = ['PaymentService']
