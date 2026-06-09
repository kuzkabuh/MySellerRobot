"""version: 1.1.0
description: Compatibility facade. Moved to app.services.account.web_password_auth_service.
updated: 2026-06-09
"""

from app.services.account.web_password_auth_service import (  # noqa: F401
    PasswordSettingsResult,
    WebPasswordAuthError,
    WebPasswordAuthService,
)

__all__ = ['PasswordSettingsResult', 'WebPasswordAuthError', 'WebPasswordAuthService']
