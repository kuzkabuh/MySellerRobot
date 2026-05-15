"""version: 1.0.0
description: Centralized exception hierarchy for the application.
updated: 2026-05-15
"""

from typing import Any


class AppError(Exception):
    """Base exception for all application errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(AppError):
    """Raised when application configuration is invalid."""


class DatabaseError(AppError):
    """Raised when database operation fails."""


class MarketplaceApiError(AppError):
    """Raised when marketplace API returns an error."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        marketplace: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details)
        self.status_code = status_code
        self.marketplace = marketplace


class RateLimitError(MarketplaceApiError):
    """Raised when API rate limit is exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: int | None = None,
        marketplace: str | None = None,
    ) -> None:
        super().__init__(message, status_code=429, marketplace=marketplace)
        self.retry_after = retry_after


class AuthenticationError(MarketplaceApiError):
    """Raised when API authentication fails."""

    def __init__(
        self,
        message: str = "Authentication failed",
        marketplace: str | None = None,
    ) -> None:
        super().__init__(message, status_code=401, marketplace=marketplace)


class ValidationError(AppError):
    """Raised when data validation fails."""

    def __init__(
        self,
        message: str,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details)
        self.field = field


class NotFoundError(AppError):
    """Raised when requested resource is not found."""


class BusinessLogicError(AppError):
    """Raised when business logic constraint is violated."""


class IntegrationError(AppError):
    """Raised when external integration fails."""


class CryptoError(AppError):
    """Raised when encryption/decryption fails."""


class TelegramError(AppError):
    """Raised when Telegram API operation fails."""
