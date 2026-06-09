"""version: 1.1.0
description: Compatibility facade. Moved to app.services.account.account_profile_service.
updated: 2026-06-09
"""

from app.services.account.account_profile_service import (  # noqa: F401
    AccountProfileService,
    SellerCabinetSnapshot,
)

__all__ = ['AccountProfileService', 'SellerCabinetSnapshot']
