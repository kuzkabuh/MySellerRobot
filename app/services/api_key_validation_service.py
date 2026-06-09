"""version: 1.1.0
description: Compatibility facade. Moved to app.services.account.api_key_validation_service.
updated: 2026-06-09
"""

from app.services.account.api_key_validation_service import (  # noqa: F401
    ApiKeyCheckResult,
    ApiKeyValidationError,
    ApiKeyValidationService,
)

__all__ = ['ApiKeyCheckResult', 'ApiKeyValidationError', 'ApiKeyValidationService']
