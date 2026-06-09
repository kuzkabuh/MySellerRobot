"""version: 1.1.0
description: Compatibility facade. Moved to app.services.account.account_service.
updated: 2026-06-09
"""

from app.services.account.account_service import (  # noqa: F401
    AccountConnectionError,
    CreateAccountCommand,
    MarketplaceAccountService,
)

__all__ = ['AccountConnectionError', 'CreateAccountCommand', 'MarketplaceAccountService']
