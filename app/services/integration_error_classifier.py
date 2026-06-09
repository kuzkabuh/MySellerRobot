"""version: 1.1.0
description: Compatibility facade. Moved to app.services.common.integration_error_classifier.
updated: 2026-06-09
"""

from app.services.common.integration_error_classifier import (  # noqa: F401
    IntegrationErrorAdvice,
    IntegrationErrorKind,
    classify_integration_error,
)

__all__ = ['IntegrationErrorAdvice', 'IntegrationErrorKind', 'classify_integration_error']
