"""version: 2.0.0
description: Tests for Release 1.6.2 — Secure & Idempotent Payment Processing.
updated: 2026-05-19
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.enums import PaymentStatus
from app.models.subscriptions import Payment
from app.services.payments.payment_service import PaymentService


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
    with patch("app.services.payments.payment_service.YooKassaClient") as mock:
        yield mock


@pytest.fixture
def payment_service(mock_session, mock_yookassa):
    """Create PaymentService with mocked dependencies."""
    with patch("app.services.payments.payment_service.get_settings") as mock_settings:
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

    payment_service.subscription_service.get_active_subscription = AsyncMock(return_value=None)
    payment_service.subscription_service.create_subscription = AsyncMock()

    yookassa_data = {"id": "test_payment_123", "status": "succeeded"}

    await payment_service.handle_payment_success(yookassa_data)

    assert payment.status == PaymentStatus.SUCCEEDED
    payment_service.subscription_service.create_subscription.assert_not_called()


@pytest.mark.asyncio
async def test_payment_success_verified_with_api(payment_service, mock_session):
    """Payment success should verify status via YooKassa API when webhook lacks status."""
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
    mock_result.scalar_one_or_none.side_effect = [payment, None]
    mock_session.execute.return_value = mock_result

    payment_service.yookassa.get_payment = AsyncMock(
        return_value={"id": "test_payment_123", "status": "succeeded"}
    )

    mock_subscription = MagicMock()
    mock_subscription.id = 1
    mock_subscription.expires_at = datetime.now(tz=UTC)
    payment_service.subscription_service.create_subscription = AsyncMock(
        return_value=mock_subscription
    )

    yookassa_data = {"id": "test_payment_123"}

    await payment_service.handle_payment_success(yookassa_data)

    payment_service.yookassa.get_payment.assert_called_once_with("test_payment_123")


@pytest.mark.asyncio
async def test_payment_success_rejected_if_verification_fails(payment_service, mock_session):
    """Payment should not be processed if API verification fails."""
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

    payment_service.yookassa.get_payment = AsyncMock(
        return_value={"id": "test_payment_123", "status": "pending"}
    )

    yookassa_data = {"id": "test_payment_123"}

    await payment_service.handle_payment_success(yookassa_data)

    assert payment.status == PaymentStatus.PENDING


@pytest.mark.asyncio
async def test_payment_success_rejects_unverified_webhook_status(payment_service, mock_session):
    """Webhook status alone must not activate a subscription."""
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

    payment_service.yookassa.get_payment = AsyncMock(
        return_value={"id": "test_payment_123", "status": "pending"}
    )
    payment_service.subscription_service.create_subscription = AsyncMock()

    yookassa_data = {"id": "test_payment_123", "status": "succeeded"}

    await payment_service.handle_payment_success(yookassa_data)

    payment_service.yookassa.get_payment.assert_called_once_with("test_payment_123")
    payment_service.subscription_service.create_subscription.assert_not_called()
    assert payment.status == PaymentStatus.PENDING


@pytest.mark.asyncio
async def test_cancel_does_not_override_succeeded_payment(payment_service, mock_session):
    """Cancelled webhook should not override already succeeded payment."""
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

    await payment_service.handle_payment_cancel(yookassa_data)

    assert payment.status == PaymentStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_duplicate_cancel_webhook_ignored(payment_service, mock_session):
    """Duplicate payment.canceled webhook should be ignored."""
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

    await payment_service.handle_payment_cancel(yookassa_data)

    assert payment.status == PaymentStatus.CANCELLED


@pytest.mark.asyncio
async def test_payment_cancel_verified_with_api(payment_service, mock_session):
    """Payment cancel should be verified with YooKassa API."""
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

    payment_service.yookassa.get_payment = AsyncMock(
        return_value={"id": "test_payment_123", "status": "canceled"}
    )

    yookassa_data = {"id": "test_payment_123", "status": "canceled"}

    await payment_service.handle_payment_cancel(yookassa_data)

    payment_service.yookassa.get_payment.assert_called_once_with("test_payment_123")
    assert payment.status == PaymentStatus.CANCELLED


@pytest.mark.asyncio
async def test_invalid_metadata_does_not_activate_subscription(payment_service, mock_session):
    """Payment with invalid metadata should not activate subscription."""
    payment = Payment(
        id=1,
        user_id=100,
        provider="yookassa",
        provider_payment_id="test_payment_123",
        amount=Decimal("490"),
        currency="RUB",
        status=PaymentStatus.PENDING,
        payment_metadata={"period": "monthly", "user_id": "100"},
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = payment
    mock_session.execute.return_value = mock_result

    payment_service.yookassa.get_payment = AsyncMock(
        return_value={"id": "test_payment_123", "status": "succeeded"}
    )
    payment_service.subscription_service.create_subscription = AsyncMock()

    yookassa_data = {"id": "test_payment_123", "status": "succeeded"}

    await payment_service.handle_payment_success(yookassa_data)

    payment_service.subscription_service.create_subscription.assert_not_called()
    assert payment.status == PaymentStatus.FAILED
    assert payment.subscription_id is None
    assert payment.payment_metadata["activation_error"] == "tier_code_missing"


@pytest.mark.asyncio
async def test_invalid_tier_marks_activation_failed(payment_service, mock_session):
    """Paid provider payment with invalid tier must be diagnosable."""
    payment = Payment(
        id=1,
        user_id=100,
        provider="yookassa",
        provider_payment_id="test_payment_123",
        amount=Decimal("490"),
        currency="RUB",
        status=PaymentStatus.PENDING,
        payment_metadata={"tier_code": "ghost", "period": "monthly", "user_id": "100"},
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = payment
    mock_session.execute.return_value = mock_result

    payment_service.yookassa.get_payment = AsyncMock(
        return_value={"id": "test_payment_123", "status": "succeeded"}
    )
    payment_service.subscription_service.create_subscription = AsyncMock(
        side_effect=ValueError("Tier ghost not found")
    )

    yookassa_data = {"id": "test_payment_123", "status": "succeeded"}

    await payment_service.handle_payment_success(yookassa_data)

    assert payment.status == PaymentStatus.FAILED
    assert payment.subscription_id is None
    assert payment.payment_metadata["activation_error"] == "subscription_activation_failed"


@pytest.mark.asyncio
async def test_user_id_mismatch_prevents_activation(payment_service, mock_session):
    """Payment with mismatched user_id should not activate subscription."""
    payment = Payment(
        id=1,
        user_id=100,
        provider="yookassa",
        provider_payment_id="test_payment_123",
        amount=Decimal("490"),
        currency="RUB",
        status=PaymentStatus.PENDING,
        payment_metadata={
            "tier_code": "basic",
            "period": "monthly",
            "user_id": "999",
        },
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = payment
    mock_session.execute.return_value = mock_result

    payment_service.yookassa.get_payment = AsyncMock(
        return_value={"id": "test_payment_123", "status": "succeeded"}
    )

    yookassa_data = {"id": "test_payment_123", "status": "succeeded"}

    await payment_service.handle_payment_success(yookassa_data)

    assert payment.status == PaymentStatus.PENDING
