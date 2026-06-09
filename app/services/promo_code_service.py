"""version: 1.1.0
description: Compatibility facade. Moved to app.services.subscriptions.promo_code_service.
updated: 2026-06-09
"""

from app.services.subscriptions.promo_code_service import (  # noqa: F401
    PromoCodeService,
    PromoValidationError,
    normalize_code,
)

__all__ = ['PromoCodeService', 'PromoValidationError', 'normalize_code']
