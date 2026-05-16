"""version: 1.0.0
description: Unit tests for integration error classification and recommendations.
updated: 2026-05-15
"""

from app.services.integration_error_classifier import (
    IntegrationErrorKind,
    classify_integration_error,
)


def test_auth_error_gets_key_recommendation() -> None:
    advice = classify_integration_error("401 Unauthorized invalid token")

    assert advice.kind == IntegrationErrorKind.AUTH
    assert "API-ключ" in advice.recommendation


def test_rate_limit_error_gets_retry_recommendation() -> None:
    advice = classify_integration_error("429 Too Many Requests")

    assert advice.kind == IntegrationErrorKind.RATE_LIMIT
    assert "повторит попытку" in advice.recommendation


def test_unknown_error_has_safe_fallback() -> None:
    advice = classify_integration_error("unexpected marketplace response")

    assert advice.kind == IntegrationErrorKind.UNKNOWN
    assert "позже" in advice.recommendation
