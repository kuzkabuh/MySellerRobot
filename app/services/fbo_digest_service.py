"""version: 1.1.0
description: Compatibility facade. Moved to app.services.alerts.fbo_digest_service.
updated: 2026-06-09
"""

from app.services.alerts.fbo_digest_service import (  # noqa: F401
    FboDigestNotification,
    FboDigestService,
)

__all__ = ['FboDigestNotification', 'FboDigestService']
