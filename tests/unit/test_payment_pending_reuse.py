"""Tests for pending payment reuse, confirmation URL handling, and reconciliation."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.enums import PaymentStatus
from app.models.subscriptions import Payment
from app.services.payment_service import PaymentService


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def mock_tier():
    tier = MagicMock()
    tier.name = "BASIC"
    tier.code = "basic"
    tier.price_monthly = Decimal("490")
    tier.price_yearly = Decimal("4900")
    return tier


def _make_result(scalar_value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_value
    return result


def _make_list_result(items):
    scalars = MagicMock()
    scalars.all.return_value = items
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


class TestPendingPaymentReuse:
    """Test reusing an existing PENDING payment returns valid confirmation_url."""

    @pytest.mark.asyncio
    async def test_reuse_returns_confirmation_url_from_metadata(self, mock_session, mock_tier):
        """When pending payment has confirmation_url in metadata, return it directly."""
        existing = Payment(
            id=1,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-existing",
            amount=Decimal("490"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={
                "tier_code": "basic",
                "period": "monthly",
                "user_id": "1",
                "confirmation_url": "https://yookassa.ru/pay/existing",
            },
        )

        mock_session.execute.side_effect = [
            _make_result(mock_tier),
            _make_result(existing),
        ]

        with patch("app.services.payment_service.get_settings") as mock_settings, \
             patch("app.services.payment_service.YooKassaClient") as mock_yk_class:
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.create_payment = AsyncMock()
            mock_yk_class.return_value = mock_yk

            service = PaymentService(mock_session)

            payment, confirmation_url = await service.create_subscription_payment(
                user_id=1,
                tier_code="basic",
                period="monthly",
                return_url="https://example.com/success",
                customer_email="user@example.com",
            )

            assert payment.id == 1
            assert confirmation_url == "https://yookassa.ru/pay/existing"
            mock_yk.create_payment.assert_not_called()

    @pytest.mark.asyncio
    async def test_reuse_fetches_confirmation_url_from_api_when_missing(self, mock_session, mock_tier):
        """When pending payment has no confirmation_url, fetch from YooKassa API."""
        existing = Payment(
            id=1,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-no-url",
            amount=Decimal("490"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={
                "tier_code": "basic",
                "period": "monthly",
                "user_id": "1",
            },
        )

        mock_session.execute.side_effect = [
            _make_result(mock_tier),
            _make_result(existing),
        ]

        with patch("app.services.payment_service.get_settings") as mock_settings, \
             patch("app.services.payment_service.YooKassaClient") as mock_yk_class:
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.get_payment = AsyncMock(return_value={
                "id": "yk-no-url",
                "confirmation": {"confirmation_url": "https://yookassa.ru/pay/fetched"},
            })
            mock_yk.create_payment = AsyncMock()
            mock_yk_class.return_value = mock_yk

            service = PaymentService(mock_session)

            payment, confirmation_url = await service.create_subscription_payment(
                user_id=1,
                tier_code="basic",
                period="monthly",
                return_url="https://example.com/success",
                customer_email="user@example.com",
            )

            assert confirmation_url == "https://yookassa.ru/pay/fetched"
            assert existing.payment_metadata["confirmation_url"] == "https://yookassa.ru/pay/fetched"

    @pytest.mark.asyncio
    async def test_reuse_returns_empty_url_when_api_fails(self, mock_session, mock_tier):
        """When API fetch fails, return empty string (handler handles fallback)."""
        existing = Payment(
            id=1,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-api-fail",
            amount=Decimal("490"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={
                "tier_code": "basic",
                "period": "monthly",
                "user_id": "1",
            },
        )

        mock_session.execute.side_effect = [
            _make_result(mock_tier),
            _make_result(existing),
        ]

        with patch("app.services.payment_service.get_settings") as mock_settings, \
             patch("app.services.payment_service.YooKassaClient") as mock_yk_class:
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.get_payment = AsyncMock(side_effect=Exception("API error"))
            mock_yk.create_payment = AsyncMock()
            mock_yk_class.return_value = mock_yk

            service = PaymentService(mock_session)

            payment, confirmation_url = await service.create_subscription_payment(
                user_id=1,
                tier_code="basic",
                period="monthly",
                return_url="https://example.com/success",
                customer_email="user@example.com",
            )

            assert confirmation_url == ""
            assert payment.id == 1

    @pytest.mark.asyncio
    async def test_new_payment_stores_confirmation_url_in_metadata(self, mock_session, mock_tier):
        """New payment should store confirmation_url in payment_metadata."""
        mock_session.execute.side_effect = [
            _make_result(mock_tier),
            _make_result(None),
        ]

        with patch("app.services.payment_service.get_settings") as mock_settings, \
             patch("app.services.payment_service.YooKassaClient") as mock_yk_class:
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.create_payment = AsyncMock(return_value={
                "id": "yk-new",
                "status": "pending",
                "amount": {"value": "490", "currency": "RUB"},
                "confirmation": {"confirmation_url": "https://yookassa.ru/pay/new"},
                "description": "Подписка MP Control — тариф BASIC, 1 месяц",
                "metadata": {},
            })
            mock_yk.get_payment = AsyncMock(return_value={})
            mock_yk_class.return_value = mock_yk

            service = PaymentService(mock_session)

            payment, confirmation_url = await service.create_subscription_payment(
                user_id=1,
                tier_code="basic",
                period="monthly",
                return_url="https://example.com/success",
                customer_email="user@example.com",
            )

            assert confirmation_url == "https://yookassa.ru/pay/new"
            assert payment.payment_metadata["confirmation_url"] == "https://yookassa.ru/pay/new"


class TestReconciliationOfStuckPayments:
    """Test reconciliation handles real-world stuck payment scenarios."""

    @pytest.mark.asyncio
    async def test_stuck_succeeded_payment_gets_activated(self, mock_session, mock_tier):
        """A payment that was paid in YooKassa but stuck as PENDING locally gets activated."""
        payment = Payment(
            id=42,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-stuck-paid",
            amount=Decimal("490"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={
                "tier_code": "basic",
                "period": "monthly",
                "user_id": "1",
                "confirmation_url": "https://yookassa.ru/pay/stuck",
            },
        )

        user = MagicMock()
        user.id = 1
        user.telegram_id = 12345
        user.timezone = "Europe/Moscow"

        mock_session.execute.side_effect = [
            _make_list_result([payment]),
            _make_result(payment),
            _make_result(mock_tier),
            _make_result(user),
        ]

        with patch("app.services.payment_service.get_settings") as mock_settings, \
             patch("app.services.payment_service.YooKassaClient") as mock_yk_class, \
             patch("app.bot.main.create_bot") as mock_create_bot:
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.get_payment = AsyncMock(return_value={
                "id": "yk-stuck-paid",
                "status": "succeeded",
                "paid": True,
                "payment_method": {"type": "bank_card"},
            })
            mock_yk_class.return_value = mock_yk

            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock()
            mock_create_bot.return_value = mock_bot

            service = PaymentService(mock_session)

            mock_sub = MagicMock()
            mock_sub.id = 100
            mock_sub.expires_at = datetime.now(tz=UTC)
            service.subscription_service.create_subscription = AsyncMock(return_value=mock_sub)

            reconciled = await service.reconcile_pending_payments()

            assert reconciled == 1
            assert payment.status == PaymentStatus.SUCCEEDED
            assert payment.paid_at is not None
            assert payment.subscription_id == 100

    @pytest.mark.asyncio
    async def test_reconciliation_idempotent_already_succeeded(self, mock_session, mock_tier):
        """Re-running reconciliation on already-succeeded payment does nothing."""
        payment = Payment(
            id=42,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-already-done",
            amount=Decimal("490"),
            currency="RUB",
            status=PaymentStatus.SUCCEEDED,
            paid_at=datetime.now(tz=UTC),
            subscription_id=50,
            payment_metadata={
                "tier_code": "basic",
                "period": "monthly",
                "user_id": "1",
            },
        )

        mock_session.execute.side_effect = [
            _make_list_result([payment]),
        ]

        with patch("app.services.payment_service.get_settings") as mock_settings, \
             patch("app.services.payment_service.YooKassaClient") as mock_yk_class:
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings

            mock_yk_class.return_value = MagicMock()
            service = PaymentService(mock_session)

            reconciled = await service.reconcile_pending_payments()

            assert reconciled == 0
            assert payment.status == PaymentStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_reconciliation_handles_canceled_payment(self, mock_session, mock_tier):
        """A payment canceled in YooKassa gets marked as CANCELLED locally."""
        payment = Payment(
            id=43,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-canceled",
            amount=Decimal("490"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={
                "tier_code": "basic",
                "period": "monthly",
                "user_id": "1",
            },
        )

        mock_session.execute.side_effect = [
            _make_list_result([payment]),
            _make_result(payment),
        ]

        with patch("app.services.payment_service.get_settings") as mock_settings, \
             patch("app.services.payment_service.YooKassaClient") as mock_yk_class:
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.get_payment = AsyncMock(return_value={
                "id": "yk-canceled",
                "status": "canceled",
            })
            mock_yk_class.return_value = mock_yk

            service = PaymentService(mock_session)

            reconciled = await service.reconcile_pending_payments()

            assert reconciled == 1
            assert payment.status == PaymentStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_reconciliation_leaves_truly_pending_unchanged(self, mock_session, mock_tier):
        """A payment still pending in YooKassa stays PENDING locally."""
        payment = Payment(
            id=44,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-still-pending",
            amount=Decimal("490"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={
                "tier_code": "basic",
                "period": "monthly",
                "user_id": "1",
            },
        )

        mock_session.execute.side_effect = [
            _make_list_result([payment]),
            _make_result(payment),
        ]

        with patch("app.services.payment_service.get_settings") as mock_settings, \
             patch("app.services.payment_service.YooKassaClient") as mock_yk_class:
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.get_payment = AsyncMock(return_value={
                "id": "yk-still-pending",
                "status": "pending",
            })
            mock_yk_class.return_value = mock_yk

            service = PaymentService(mock_session)

            reconciled = await service.reconcile_pending_payments()

            assert reconciled == 0
            assert payment.status == PaymentStatus.PENDING

    @pytest.mark.asyncio
    async def test_reconciliation_handles_missing_payment_id_gracefully(self, mock_session, mock_tier):
        """Payment without provider_payment_id is logged and skipped."""
        payment = Payment(
            id=45,
            user_id=1,
            provider="yookassa",
            provider_payment_id="",
            amount=Decimal("490"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={"tier_code": "basic", "period": "monthly", "user_id": "1"},
        )

        mock_session.execute.side_effect = [
            _make_list_result([payment]),
            _make_result(payment),
        ]

        with patch("app.services.payment_service.get_settings") as mock_settings, \
             patch("app.services.payment_service.YooKassaClient") as mock_yk_class:
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.get_payment = AsyncMock(side_effect=Exception("No payment ID"))
            mock_yk_class.return_value = mock_yk

            service = PaymentService(mock_session)

            reconciled = await service.reconcile_pending_payments()

            assert reconciled == 0
            assert payment.status == PaymentStatus.PENDING
