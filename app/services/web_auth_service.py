"""version: 1.1.0
description: Compatibility facade. Moved to app.services.account.web_auth_service.
updated: 2026-06-09
"""

from app.services.account.web_auth_service import (  # noqa: F401
    WebAuthService,
    WebLoginLink,
    WebSession,
)

__all__ = ['WebAuthService', 'WebLoginLink', 'WebSession']
