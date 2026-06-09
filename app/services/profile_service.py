"""version: 1.1.0
description: Compatibility facade. Moved to app.services.account.profile_service.
updated: 2026-06-09
"""

from app.services.account.profile_service import (  # noqa: F401
    ProfileData,
    ProfileService,
    ProfileUpdateData,
    ProfileValidationError,
)

__all__ = ['ProfileData', 'ProfileService', 'ProfileUpdateData', 'ProfileValidationError']
