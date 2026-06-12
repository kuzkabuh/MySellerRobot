"""Tests for YooKassa webhook processing, reconciliation, and payment flow."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.enums import PaymentStatus
from app.models.subscriptions import Payment
from app.services.payments.payment_service import PaymentService


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


class TestWebhookPaymentSucceeded:
    """Test payment.succeeded webhook updates payment and activates subscription."""

    @pytest.mark.asyncio
    async def test_webhook_updates_payment_to_succeeded(self, mock_session, mock_tier):
        payment = Payment(
            id=1,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-123",
            amount=Decimal("490"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={"tier_code": "basic", "period": "monthly", "user_id": "1"},
        )

        user = MagicMock()
        user.id = 1
        user.telegram_id = 12345
        user.timezone = "Europe/Moscow"

        mock_session.execute.side_effect = [
            _make_result(payment),
            _make_result(mock_tier),
            _make_result(user),
        ]

        with (
            patch("app.services.payments.payment_service.get_settings") as mock_settings,
            patch("app.services.payments.payment_service.YooKassaClient") as mock_yk_class,
            patch("app.bot.main.create_bot") as mock_create_bot,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.get_payment = AsyncMock(
                return_value={
                    "id": "yk-123",
                    "status": "succeeded",
                    "payment_method": {"type": "bank_card"},
                }
            )
            mock_yk_class.return_value = mock_yk

            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock()
            mock_create_bot.return_value = mock_bot

            service = PaymentService(mock_session)

            mock_sub = MagicMock()
            mock_sub.id = 10
            mock_sub.expires_at = datetime.now(tz=UTC)
            service.subscription_service.create_subscription = AsyncMock(return_value=mock_sub)

            await service.handle_payment_success(
                {
                    "id": "yk-123",
                    "status": "succeeded",
                    "paid": True,
                    "payment_method": {"type": "bank_card"},
                }
            )

            assert payment.status == PaymentStatus.SUCCEEDED
            assert payment.paid_at is not None
            assert payment.subscription_id == 10

    @pytest.mark.asyncio
    async def test_webhook_activates_subscription(self, mock_session, mock_tier):
        payment = Payment(
            id=1,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-456",
            amount=Decimal("490"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={"tier_code": "basic", "period": "monthly", "user_id": "1"},
        )

        user = MagicMock()
        user.id = 1
        user.telegram_id = 12345
        user.timezone = "Europe/Moscow"

        mock_session.execute.side_effect = [
            _make_result(payment),
            _make_result(mock_tier),
            _make_result(user),
        ]

        with (
            patch("app.services.payments.payment_service.get_settings") as mock_settings,
            patch("app.services.payments.payment_service.YooKassaClient") as mock_yk_class,
            patch("app.bot.main.create_bot") as mock_create_bot,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.get_payment = AsyncMock(
                return_value={
                    "id": "yk-456",
                    "status": "succeeded",
                }
            )
            mock_yk_class.return_value = mock_yk

            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock()
            mock_create_bot.return_value = mock_bot

            service = PaymentService(mock_session)

            mock_sub = MagicMock()
            mock_sub.id = 20
            mock_sub.expires_at = datetime.now(tz=UTC)
            service.subscription_service.create_subscription = AsyncMock(return_value=mock_sub)

            await service.handle_payment_success({"id": "yk-456", "status": "succeeded"})

            service.subscription_service.create_subscription.assert_called_once_with(
                user_id=1,
                tier_code="basic",
                period="monthly",
                is_trial=False,
                payment_provider="yookassa",
                payment_id="yk-456",
            )

    @pytest.mark.asyncio
    async def test_duplicate_webhook_does_not_reactivate(self, mock_session, mock_tier):
        payment = Payment(
            id=1,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-789",
            amount=Decimal("490"),
            currency="RUB",
            status=PaymentStatus.SUCCEEDED,
            paid_at=datetime.now(tz=UTC),
            subscription_id=5,
            payment_metadata={"tier_code": "basic", "period": "monthly", "user_id": "1"},
        )

        mock_session.execute.side_effect = [
            _make_result(payment),
        ]

        with (
            patch("app.services.payments.payment_service.get_settings") as mock_settings,
            patch("app.services.payments.payment_service.YooKassaClient") as mock_yk_class,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings

            mock_yk_class.return_value = MagicMock()
            service = PaymentService(mock_session)
            service.subscription_service.create_subscription = AsyncMock()

            await service.handle_payment_success({"id": "yk-789", "status": "succeeded"})

            service.subscription_service.create_subscription.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_payment_id_no_crash(self, mock_session, mock_tier):
        mock_session.execute.side_effect = [
            _make_result(None),
        ]

        with (
            patch("app.services.payments.payment_service.get_settings") as mock_settings,
            patch("app.services.payments.payment_service.YooKassaClient") as mock_yk_class,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings

            mock_yk_class.return_value = MagicMock()
            service = PaymentService(mock_session)

            await service.handle_payment_success({"id": "nonexistent", "status": "succeeded"})


class TestWebhookPaymentCanceled:
    """Test payment.canceled webhook marks payment as cancelled."""

    @pytest.mark.asyncio
    async def test_webhook_cancels_payment(self, mock_session, mock_tier):
        payment = Payment(
            id=1,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-cancel",
            amount=Decimal("490"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={"tier_code": "basic", "period": "monthly", "user_id": "1"},
        )

        mock_session.execute.side_effect = [
            _make_result(payment),
        ]

        with (
            patch("app.services.payments.payment_service.get_settings") as mock_settings,
            patch("app.services.payments.payment_service.YooKassaClient") as mock_yk_class,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.get_payment = AsyncMock(
                return_value={
                    "id": "yk-cancel",
                    "status": "canceled",
                }
            )
            mock_yk_class.return_value = mock_yk

            service = PaymentService(mock_session)

            await service.handle_payment_cancel({"id": "yk-cancel", "status": "canceled"})

            assert payment.status == PaymentStatus.CANCELLED


class TestReconciliation:
    """Test reconciliation of stuck PENDING payments."""

    @pytest.mark.asyncio
    async def test_reconciliation_updates_succeeded_payment(self, mock_session, mock_tier):
        payment = Payment(
            id=1,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-recon",
            amount=Decimal("490"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={"tier_code": "basic", "period": "monthly", "user_id": "1"},
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

        with (
            patch("app.services.payments.payment_service.get_settings") as mock_settings,
            patch("app.services.payments.payment_service.YooKassaClient") as mock_yk_class,
            patch("app.bot.main.create_bot") as mock_create_bot,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.get_payment = AsyncMock(
                return_value={
                    "id": "yk-recon",
                    "status": "succeeded",
                    "payment_method": {"type": "bank_card"},
                }
            )
            mock_yk_class.return_value = mock_yk

            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock()
            mock_create_bot.return_value = mock_bot

            service = PaymentService(mock_session)

            mock_sub = MagicMock()
            mock_sub.id = 30
            mock_sub.expires_at = datetime.now(tz=UTC)
            service.subscription_service.create_subscription = AsyncMock(return_value=mock_sub)

            reconciled = await service.reconcile_pending_payments()

            assert reconciled == 1
            assert payment.status == PaymentStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_reconciliation_updates_canceled_payment(self, mock_session, mock_tier):
        payment = Payment(
            id=1,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-recon-cancel",
            amount=Decimal("490"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={"tier_code": "basic", "period": "monthly", "user_id": "1"},
        )

        mock_session.execute.side_effect = [
            _make_list_result([payment]),
            _make_result(payment),
        ]

        with (
            patch("app.services.payments.payment_service.get_settings") as mock_settings,
            patch("app.services.payments.payment_service.YooKassaClient") as mock_yk_class,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.get_payment = AsyncMock(
                return_value={
                    "id": "yk-recon-cancel",
                    "status": "canceled",
                }
            )
            mock_yk_class.return_value = mock_yk

            service = PaymentService(mock_session)

            reconciled = await service.reconcile_pending_payments()

            assert reconciled == 1
            assert payment.status == PaymentStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_reconciliation_no_pending_payments(self, mock_session):
        mock_session.execute.return_value = _make_list_result([])

        with (
            patch("app.services.payments.payment_service.get_settings") as mock_settings,
            patch("app.services.payments.payment_service.YooKassaClient") as mock_yk_class,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings

            mock_yk_class.return_value = MagicMock()
            service = PaymentService(mock_session)

            reconciled = await service.reconcile_pending_payments()

            assert reconciled == 0
