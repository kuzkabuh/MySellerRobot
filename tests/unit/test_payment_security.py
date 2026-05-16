"""version: 1.0.0
description: Tests for Release 1.6.2 — Secure & Idempotent Payment Processing.
updated: 2026-05-16
"""

import pytest
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.enums import PaymentStatus
from app.models.subscriptions import Payment, SubscriptionTier, UserSubscription
from app.services.payment_service import PaymentService


@pytest.fixture
def mock_session():
    """Mock async session."""
    session = MagicMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def mock_yookassa():
    """Mock YooKassa client."""
    with patch("app.services.payment_service.YooKassaClient") as mock:
        yield mock


@pytest.fixture
def payment_service(mock_session, mock_yookassa):
    """Create PaymentService with mocked dependencies."""
    with patch("app.services.payment_service.get_settings") as mock_settings:
        settings = MagicMock()
        settings.yookassa_shop_id = "test_shop"
        settings.yookassa_secret_key.get_secret_value.return_value = "test_secret"
        mock_settings.return_value = settings

        service = PaymentService(mock_session)
        service.yookassa = mock_yookassa.return_value
        return service


@pytest.mark.asyncio
async def test_duplicate_success_webhook_ignored(payment_service, mock_session):
    """Duplicate payment.succeeded webhook should be ignored."""
    # Arrange: payment already succeeded
    payment = Payment(
        id=1,
        user_id=100,
        provider="yookassa",
        provider_payment_id="test_payment_123",
        amount=Decimal("490"),
        currency="RUB",
        status=PaymentStatus.SUCCEEDED,
        paid_at=datetime.now(tz=UTC),
        payment_metadata={"tier_code": "basic", "period": "monthly", "user_id": "100"},
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = payment
    mock_session.execute.return_value = mock_result

    # Mock subscription service methods
    payment_service.subscription_service.get_active_subscription = AsyncMock(return_value=None)
    payment_service.subscription_service.create_subscription = AsyncMock()

    yookassa_data = {"id": "test_payment_123", "status": "succeeded"}

    # Act
    await payment_service.handle_payment_success(yookassa_data)

    # Assert: status should remain SUCCEEDED, no subscription created
    assert payment.status == PaymentStatus.SUCCEEDED
    payment_service.subscription_service.create_subscription.assert_not_called()


@pytest.mark.asyncio
async def test_payment_success_verified_with_api(payment_service, mock_session):
    """Payment success should be verified with YooKassa API."""
    # Arrange
    payment = Payment(
        id=1,
        user_id=100,
        provider="yookassa",
        provider_payment_id="test_payment_123",
        amount=Decimal("490"),
        currency="RUB",
        status=PaymentStatus.PENDING,
        payment_metadata={"tier_code": "basic", "period": "monthly", "user_id": "100"},
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = payment
    mock_session.execute.return_value = mock_result

    # Mock YooKassa API verification
    payment_service.yookassa.get_payment = AsyncMock(
        return_value={"id": "test_payment_123", "status": "succeeded"}
    )

    # Mock subscription service
    payment_service.subscription_service.get_active_subscription = AsyncMock(return_value=None)
    payment_service.subscription_service.create_subscription = AsyncMock(
        return_value=MagicMock(id=1)
    )

    yookassa_data = {"id": "test_payment_123", "status": "succeeded"}

    # Act
    await payment_service.handle_payment_success(yookassa_data)

    # Assert: API verification was called
    payment_service.yookassa.get_payment.assert_called_once_with("test_payment_123")


@pytest.mark.asyncio
async def test_payment_success_rejected_if_verification_fails(payment_service, mock_session):
    """Payment should not be processed if API verification fails."""
    # Arrange
    payment = Payment(
        id=1,
        user_id=100,
        provider="yookassa",
        provider_payment_id="test_payment_123",
        amount=Decimal("490"),
        currency="RUB",
        status=PaymentStatus.PENDING,
        payment_metadata={"tier_code": "basic", "period": "monthly", "user_id": "100"},
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = payment
    mock_session.execute.return_value = mock_result

    # Mock YooKassa API returns different status
    payment_service.yookassa.get_payment = AsyncMock(
        return_value={"id": "test_payment_123", "status": "pending"}
    )

    yookassa_data = {"id": "test_payment_123", "status": "succeeded"}

    # Act
    await payment_service.handle_payment_success(yookassa_data)

    # Assert: payment status should remain PENDING
    assert payment.status == PaymentStatus.PENDING


@pytest.mark.asyncio
async def test_cancel_does_not_override_succeeded_payment(payment_service, mock_session):
    """Cancelled webhook should not override already succeeded payment."""
    # Arrange: payment already succeeded
    payment = Payment(
        id=1,
        user_id=100,
        provider="yookassa",
        provider_payment_id="test_payment_123",
        amount=Decimal("490"),
        currency="RUB",
        status=PaymentStatus.SUCCEEDED,
        paid_at=datetime.now(tz=UTC),
        payment_metadata={"tier_code": "basic", "period": "monthly", "user_id": "100"},
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = payment
    mock_session.execute.return_value = mock_result

    yookassa_data = {"id": "test_payment_123", "status": "canceled"}

    # Act
    await payment_service.handle_payment_cancel(yookassa_data)

    # Assert: status should remain SUCCEEDED
    assert payment.status == PaymentStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_duplicate_cancel_webhook_ignored(payment_service, mock_session):
    """Duplicate payment.canceled webhook should be ignored."""
    # Arrange: payment already cancelled
    payment = Payment(
        id=1,
        user_id=100,
        provider="yookassa",
        provider_payment_id="test_payment_123",
        amount=Decimal("490"),
        currency="RUB",
        status=PaymentStatus.CANCELLED,
        payment_metadata={"tier_code": "basic", "period": "monthly", "user_id": "100"},
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = payment
    mock_session.execute.return_value = mock_result

    yookassa_data = {"id": "test_payment_123", "status": "canceled"}

    # Act
    await payment_service.handle_payment_cancel(yookassa_data)

    # Assert: status should remain CANCELLED
    assert payment.status == PaymentStatus.CANCELLED


@pytest.mark.asyncio
async def test_payment_cancel_verified_with_api(payment_service, mock_session):
    """Payment cancel should be verified with YooKassa API."""
    # Arrange
    payment = Payment(
        id=1,
        user_id=100,
        provider="yookassa",
        provider_payment_id="test_payment_123",
        amount=Decimal("490"),
        currency="RUB",
        status=PaymentStatus.PENDING,
        payment_metadata={"tier_code": "basic", "period": "monthly", "user_id": "100"},
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = payment
    mock_session.execute.return_value = mock_result

    # Mock YooKassa API verification
    payment_service.yookassa.get_payment = AsyncMock(
        return_value={"id": "test_payment_123", "status": "canceled"}
    )

    yookassa_data = {"id": "test_payment_123", "status": "canceled"}

    # Act
    await payment_service.handle_payment_cancel(yookassa_data)

    # Assert: API verification was called
    payment_service.yookassa.get_payment.assert_called_once_with("test_payment_123")
    assert payment.status == PaymentStatus.CANCELLED


@pytest.mark.asyncio
async def test_invalid_metadata_does_not_activate_subscription(payment_service, mock_session):
    """Payment with invalid metadata should not activate subscription."""
    # Arrange: payment with missing tier_code
    payment = Payment(
        id=1,
        user_id=100,
        provider="yookassa",
        provider_payment_id="test_payment_123",
        amount=Decimal("490"),
        currency="RUB",
        status=PaymentStatus.PENDING,
        payment_metadata={"period": "monthly", "user_id": "100"},  # missing tier_code
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = payment
    mock_session.execute.return_value = mock_result

    # Mock YooKassa API verification
    payment_service.yookassa.get_payment = AsyncMock(
        return_value={"id": "test_payment_123", "status": "succeeded"}
    )

    yookassa_data = {"id": "test_payment_123", "status": "succeeded"}

    # Act
    await payment_service.handle_payment_success(yookassa_data)

    # Assert: no subscription created
    assert payment.status == PaymentStatus.PENDING  # Should not be updated


@pytest.mark.asyncio
async def test_user_id_mismatch_prevents_activation(payment_service, mock_session):
    """Payment with mismatched user_id should not activate subscription."""
    # Arrange: payment with mismatched user_id in metadata
    payment = Payment(
        id=1,
        user_id=100,
        provider="yookassa",
        provider_payment_id="test_payment_123",
        amount=Decimal("490"),
        currency="RUB",
        status=PaymentStatus.PENDING,
        payment_metadata={"tier_code": "basic", "period": "monthly", "user_id": "999"},  # wrong user
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = payment
    mock_session.execute.return_value = mock_result

    # Mock YooKassa API verification
    payment_service.yookassa.get_payment = AsyncMock(
        return_value={"id": "test_payment_123", "status": "succeeded"}
    )

    yookassa_data = {"id": "test_payment_123", "status": "succeeded"}

    # Act
    await payment_service.handle_payment_success(yookassa_data)

    # Assert: payment should not be processed
    assert payment.status == PaymentStatus.PENDING
