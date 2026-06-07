"""Comprehensive post-payment flow tests.

Covers:
1. BASIC monthly activation
2. BASIC yearly activation
3. PRO monthly activation
4. PRO yearly activation
5. Tier/period from Payment metadata (not UI state)
6. Duplicate webhook idempotency
7. Reconciliation of old PENDING payments
8. Missing tier_code/period in metadata
9. Unknown payment_id handling
10. Pending payment reuse only matches same tier+period
"""

from datetime import UTC, datetime, timedelta
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


def _make_basic_tier():
    tier = MagicMock()
    tier.id = 1
    tier.code = "basic"
    tier.name = "BASIC"
    tier.price_monthly = Decimal("490")
    tier.price_yearly = Decimal("4900")
    return tier


def _make_pro_tier():
    tier = MagicMock()
    tier.id = 2
    tier.code = "pro"
    tier.name = "PRO"
    tier.price_monthly = Decimal("1490")
    tier.price_yearly = Decimal("14900")
    return tier


def _make_user(telegram_id=12345, timezone="Europe/Moscow"):
    user = MagicMock()
    user.id = 1
    user.telegram_id = telegram_id
    user.timezone = timezone
    return user


def _make_succeeded_yookassa_mock():
    client = MagicMock()
    client.get_payment = AsyncMock(
        side_effect=lambda payment_id: {
            "id": payment_id,
            "status": "succeeded",
            "payment_method": {"type": "bank_card"},
        }
    )
    return client


class TestBasicMonthlyActivation:
    """Test 1: BASIC monthly payment activates correct subscription."""

    @pytest.mark.asyncio
    async def test_basic_monthly_activates_correct_tier_and_period(self, mock_session):
        payment = Payment(
            id=1,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-basic-monthly",
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
            _make_result(payment),
            _make_result(_make_basic_tier()),
            _make_result(_make_user()),
        ]

        with (
            patch("app.services.payment_service.get_settings") as mock_settings,
            patch("app.services.payment_service.YooKassaClient") as mock_yk_class,
            patch("app.bot.main.create_bot") as mock_create_bot,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings
            mock_yk_class.return_value = _make_succeeded_yookassa_mock()
            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock()
            mock_create_bot.return_value = mock_bot

            service = PaymentService(mock_session)

            future = datetime.now(tz=UTC) + timedelta(days=30)
            mock_sub = MagicMock()
            mock_sub.id = 10
            mock_sub.expires_at = future
            service.subscription_service.create_subscription = AsyncMock(return_value=mock_sub)

            await service.handle_payment_success(
                {
                    "id": "yk-basic-monthly",
                    "status": "succeeded",
                    "payment_method": {"type": "bank_card"},
                }
            )

            service.subscription_service.create_subscription.assert_called_once_with(
                user_id=1,
                tier_code="basic",
                period="monthly",
                is_trial=False,
                payment_provider="yookassa",
                payment_id="yk-basic-monthly",
            )
            assert payment.status == PaymentStatus.SUCCEEDED
            assert payment.paid_at is not None
            assert payment.subscription_id == 10


class TestBasicYearlyActivation:
    """Test 2: BASIC yearly payment activates correct subscription."""

    @pytest.mark.asyncio
    async def test_basic_yearly_activates_correct_tier_and_period(self, mock_session):
        payment = Payment(
            id=2,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-basic-yearly",
            amount=Decimal("4900"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={
                "tier_code": "basic",
                "period": "yearly",
                "user_id": "1",
            },
        )

        mock_session.execute.side_effect = [
            _make_result(payment),
            _make_result(_make_basic_tier()),
            _make_result(_make_user()),
        ]

        with (
            patch("app.services.payment_service.get_settings") as mock_settings,
            patch("app.services.payment_service.YooKassaClient") as mock_yk_class,
            patch("app.bot.main.create_bot") as mock_create_bot,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings
            mock_yk_class.return_value = _make_succeeded_yookassa_mock()
            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock()
            mock_create_bot.return_value = mock_bot

            service = PaymentService(mock_session)

            future = datetime.now(tz=UTC) + timedelta(days=365)
            mock_sub = MagicMock()
            mock_sub.id = 20
            mock_sub.expires_at = future
            service.subscription_service.create_subscription = AsyncMock(return_value=mock_sub)

            await service.handle_payment_success(
                {
                    "id": "yk-basic-yearly",
                    "status": "succeeded",
                    "payment_method": {"type": "bank_card"},
                }
            )

            service.subscription_service.create_subscription.assert_called_once_with(
                user_id=1,
                tier_code="basic",
                period="yearly",
                is_trial=False,
                payment_provider="yookassa",
                payment_id="yk-basic-yearly",
            )
            assert payment.status == PaymentStatus.SUCCEEDED


class TestProMonthlyActivation:
    """Test 3: PRO monthly payment activates PRO, not BASIC."""

    @pytest.mark.asyncio
    async def test_pro_monthly_activates_pro_not_basic(self, mock_session):
        payment = Payment(
            id=3,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-pro-monthly",
            amount=Decimal("1490"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={
                "tier_code": "pro",
                "period": "monthly",
                "user_id": "1",
            },
        )

        mock_session.execute.side_effect = [
            _make_result(payment),
            _make_result(_make_pro_tier()),
            _make_result(_make_user()),
        ]

        with (
            patch("app.services.payment_service.get_settings") as mock_settings,
            patch("app.services.payment_service.YooKassaClient") as mock_yk_class,
            patch("app.bot.main.create_bot") as mock_create_bot,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings
            mock_yk_class.return_value = _make_succeeded_yookassa_mock()
            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock()
            mock_create_bot.return_value = mock_bot

            service = PaymentService(mock_session)

            future = datetime.now(tz=UTC) + timedelta(days=30)
            mock_sub = MagicMock()
            mock_sub.id = 30
            mock_sub.expires_at = future
            service.subscription_service.create_subscription = AsyncMock(return_value=mock_sub)

            await service.handle_payment_success(
                {
                    "id": "yk-pro-monthly",
                    "status": "succeeded",
                    "payment_method": {"type": "bank_card"},
                }
            )

            call_kwargs = service.subscription_service.create_subscription.call_args.kwargs
            assert call_kwargs["tier_code"] == "pro"
            assert call_kwargs["period"] == "monthly"
            assert payment.status == PaymentStatus.SUCCEEDED


class TestProYearlyActivation:
    """Test 4: PRO yearly payment activates PRO yearly."""

    @pytest.mark.asyncio
    async def test_pro_yearly_activates_pro_yearly(self, mock_session):
        payment = Payment(
            id=4,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-pro-yearly",
            amount=Decimal("14900"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={
                "tier_code": "pro",
                "period": "yearly",
                "user_id": "1",
            },
        )

        mock_session.execute.side_effect = [
            _make_result(payment),
            _make_result(_make_pro_tier()),
            _make_result(_make_user()),
        ]

        with (
            patch("app.services.payment_service.get_settings") as mock_settings,
            patch("app.services.payment_service.YooKassaClient") as mock_yk_class,
            patch("app.bot.main.create_bot") as mock_create_bot,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings
            mock_yk_class.return_value = _make_succeeded_yookassa_mock()
            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock()
            mock_create_bot.return_value = mock_bot

            service = PaymentService(mock_session)

            future = datetime.now(tz=UTC) + timedelta(days=365)
            mock_sub = MagicMock()
            mock_sub.id = 40
            mock_sub.expires_at = future
            service.subscription_service.create_subscription = AsyncMock(return_value=mock_sub)

            await service.handle_payment_success(
                {
                    "id": "yk-pro-yearly",
                    "status": "succeeded",
                    "payment_method": {"type": "bank_card"},
                }
            )

            call_kwargs = service.subscription_service.create_subscription.call_args.kwargs
            assert call_kwargs["tier_code"] == "pro"
            assert call_kwargs["period"] == "yearly"


class TestMetadataAsSourceOfTruth:
    """Test 5: Activation uses tier_code/period from Payment metadata, not UI state."""

    @pytest.mark.asyncio
    async def test_activation_uses_metadata_not_ui_state(self, mock_session):
        """Even if UI showed different tier, metadata is the source of truth."""
        payment = Payment(
            id=5,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-metadata-truth",
            amount=Decimal("1490"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={
                "tier_code": "pro",
                "period": "yearly",
                "user_id": "1",
            },
        )

        mock_session.execute.side_effect = [
            _make_result(payment),
            _make_result(_make_pro_tier()),
            _make_result(_make_user()),
        ]

        with (
            patch("app.services.payment_service.get_settings") as mock_settings,
            patch("app.services.payment_service.YooKassaClient") as mock_yk_class,
            patch("app.bot.main.create_bot") as mock_create_bot,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings
            mock_yk_class.return_value = _make_succeeded_yookassa_mock()
            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock()
            mock_create_bot.return_value = mock_bot

            service = PaymentService(mock_session)

            mock_sub = MagicMock()
            mock_sub.id = 50
            mock_sub.expires_at = datetime.now(tz=UTC) + timedelta(days=365)
            service.subscription_service.create_subscription = AsyncMock(return_value=mock_sub)

            await service.handle_payment_success(
                {
                    "id": "yk-metadata-truth",
                    "status": "succeeded",
                    "payment_method": {"type": "bank_card"},
                }
            )

            call_kwargs = service.subscription_service.create_subscription.call_args.kwargs
            assert call_kwargs["tier_code"] == "pro"
            assert call_kwargs["period"] == "yearly"


class TestDuplicateWebhookIdempotency:
    """Test 6: Duplicate webhook does not reactivate subscription."""

    @pytest.mark.asyncio
    async def test_duplicate_webhook_no_reactivation(self, mock_session):
        payment = Payment(
            id=6,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-duplicate",
            amount=Decimal("490"),
            currency="RUB",
            status=PaymentStatus.SUCCEEDED,
            paid_at=datetime.now(tz=UTC),
            subscription_id=60,
            payment_metadata={
                "tier_code": "basic",
                "period": "monthly",
                "user_id": "1",
            },
        )

        mock_session.execute.side_effect = [
            _make_result(payment),
        ]

        with (
            patch("app.services.payment_service.get_settings") as mock_settings,
            patch("app.services.payment_service.YooKassaClient") as mock_yk_class,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings
            mock_yk_class.return_value = _make_succeeded_yookassa_mock()

            service = PaymentService(mock_session)
            service.subscription_service.create_subscription = AsyncMock()

            await service.handle_payment_success(
                {
                    "id": "yk-duplicate",
                    "status": "succeeded",
                }
            )

            service.subscription_service.create_subscription.assert_not_called()


class TestReconciliationOfOldPendingPayments:
    """Test 7: Reconciliation finds succeeded payments and activates correct subscription."""

    @pytest.mark.asyncio
    async def test_reconciliation_activates_correct_subscription(self, mock_session):
        payment = Payment(
            id=7,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-recon-old",
            amount=Decimal("4900"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={
                "tier_code": "basic",
                "period": "yearly",
                "user_id": "1",
            },
        )

        mock_session.execute.side_effect = [
            _make_list_result([payment]),
            _make_result(payment),
            _make_result(_make_basic_tier()),
            _make_result(_make_user()),
        ]

        with (
            patch("app.services.payment_service.get_settings") as mock_settings,
            patch("app.services.payment_service.YooKassaClient") as mock_yk_class,
            patch("app.bot.main.create_bot") as mock_create_bot,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.get_payment = AsyncMock(
                return_value={
                    "id": "yk-recon-old",
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
            mock_sub.id = 70
            mock_sub.expires_at = datetime.now(tz=UTC) + timedelta(days=365)
            service.subscription_service.create_subscription = AsyncMock(return_value=mock_sub)

            reconciled = await service.reconcile_pending_payments()

            assert reconciled == 1
            assert payment.status == PaymentStatus.SUCCEEDED
            assert payment.paid_at is not None
            assert payment.subscription_id == 70

            call_kwargs = service.subscription_service.create_subscription.call_args.kwargs
            assert call_kwargs["tier_code"] == "basic"
            assert call_kwargs["period"] == "yearly"


class TestMissingTierCodeInMetadata:
    """Test 8: Missing tier_code in metadata does not activate subscription erroneously."""

    @pytest.mark.asyncio
    async def test_missing_tier_code_no_activation(self, mock_session):
        payment = Payment(
            id=8,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-no-tier",
            amount=Decimal("490"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={
                "period": "monthly",
                "user_id": "1",
            },
        )

        mock_session.execute.side_effect = [
            _make_result(payment),
        ]

        with (
            patch("app.services.payment_service.get_settings") as mock_settings,
            patch("app.services.payment_service.YooKassaClient") as mock_yk_class,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings
            mock_yk_class.return_value = _make_succeeded_yookassa_mock()

            service = PaymentService(mock_session)
            service.subscription_service.create_subscription = AsyncMock()

            await service.handle_payment_success(
                {
                    "id": "yk-no-tier",
                    "status": "succeeded",
                    "payment_method": {"type": "bank_card"},
                }
            )

            service.subscription_service.create_subscription.assert_not_called()
            assert payment.status == PaymentStatus.FAILED
            assert payment.payment_metadata["activation_error"] == "tier_code_missing"
            assert payment.paid_at is not None
            assert payment.subscription_id is None


class TestMissingPeriodInMetadata:
    """Test 8b: Missing period in metadata defaults to monthly with warning."""

    @pytest.mark.asyncio
    async def test_missing_period_defaults_to_monthly(self, mock_session):
        payment = Payment(
            id=81,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-no-period",
            amount=Decimal("490"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={
                "tier_code": "basic",
                "user_id": "1",
            },
        )

        mock_session.execute.side_effect = [
            _make_result(payment),
            _make_result(_make_basic_tier()),
            _make_result(_make_user()),
        ]

        with (
            patch("app.services.payment_service.get_settings") as mock_settings,
            patch("app.services.payment_service.YooKassaClient") as mock_yk_class,
            patch("app.bot.main.create_bot") as mock_create_bot,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings
            mock_yk_class.return_value = _make_succeeded_yookassa_mock()
            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock()
            mock_create_bot.return_value = mock_bot

            service = PaymentService(mock_session)

            mock_sub = MagicMock()
            mock_sub.id = 81
            mock_sub.expires_at = datetime.now(tz=UTC) + timedelta(days=30)
            service.subscription_service.create_subscription = AsyncMock(return_value=mock_sub)

            await service.handle_payment_success(
                {
                    "id": "yk-no-period",
                    "status": "succeeded",
                    "payment_method": {"type": "bank_card"},
                }
            )

            call_kwargs = service.subscription_service.create_subscription.call_args.kwargs
            assert call_kwargs["tier_code"] == "basic"
            assert call_kwargs["period"] == "monthly"
            assert payment.status == PaymentStatus.SUCCEEDED


class TestUnknownPaymentId:
    """Test 9: Unknown payment_id does not crash, logs warning."""

    @pytest.mark.asyncio
    async def test_unknown_payment_id_no_crash(self, mock_session):
        mock_session.execute.side_effect = [
            _make_result(None),
        ]

        with (
            patch("app.services.payment_service.get_settings") as mock_settings,
            patch("app.services.payment_service.YooKassaClient") as mock_yk_class,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings
            mock_yk_class.return_value = _make_succeeded_yookassa_mock()

            service = PaymentService(mock_session)

            await service.handle_payment_success(
                {
                    "id": "nonexistent-payment",
                    "status": "succeeded",
                }
            )


class TestPendingPaymentReuseByTierAndPeriod:
    """Test 10: Pending payment reuse only matches same tier+period."""

    @pytest.mark.asyncio
    async def test_different_tier_creates_new_payment(self, mock_session):
        """User has pending BASIC monthly, tries to pay for PRO monthly.

        Should create a NEW payment for PRO, not reuse the BASIC one.
        """
        Payment(
            id=100,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-basic-pending",
            amount=Decimal("490"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={
                "tier_code": "basic",
                "period": "monthly",
                "user_id": "1",
                "confirmation_url": "https://yookassa.ru/pay/basic",
            },
        )

        mock_session.execute.side_effect = [
            _make_result(_make_pro_tier()),
            _make_result(None),
        ]

        with (
            patch("app.services.payment_service.get_settings") as mock_settings,
            patch("app.services.payment_service.YooKassaClient") as mock_yk_class,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.create_payment = AsyncMock(
                return_value={
                    "id": "yk-pro-new",
                    "status": "pending",
                    "confirmation": {"confirmation_url": "https://yookassa.ru/pay/pro"},
                    "description": "Подписка MP Control — тариф PRO, 1 месяц",
                    "metadata": {},
                }
            )
            mock_yk_class.return_value = mock_yk

            service = PaymentService(mock_session)

            payment, confirmation_url = await service.create_subscription_payment(
                user_id=1,
                tier_code="pro",
                period="monthly",
                return_url="https://example.com/success",
                customer_email="user@example.com",
            )

            assert payment.provider_payment_id == "yk-pro-new"
            assert confirmation_url == "https://yookassa.ru/pay/pro"
            assert payment.payment_metadata["tier_code"] == "pro"
            assert payment.payment_metadata["period"] == "monthly"

    @pytest.mark.asyncio
    async def test_same_tier_different_period_creates_new_payment(self, mock_session):
        """User has pending BASIC monthly, tries to pay for BASIC yearly.

        Should create a NEW payment for BASIC yearly.
        """
        Payment(
            id=101,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-basic-monthly-pending",
            amount=Decimal("490"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={
                "tier_code": "basic",
                "period": "monthly",
                "user_id": "1",
                "confirmation_url": "https://yookassa.ru/pay/basic-monthly",
            },
        )

        mock_session.execute.side_effect = [
            _make_result(_make_basic_tier()),
            _make_result(None),
        ]

        with (
            patch("app.services.payment_service.get_settings") as mock_settings,
            patch("app.services.payment_service.YooKassaClient") as mock_yk_class,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.create_payment = AsyncMock(
                return_value={
                    "id": "yk-basic-yearly-new",
                    "status": "pending",
                    "confirmation": {"confirmation_url": "https://yookassa.ru/pay/basic-yearly"},
                    "description": "Подписка MP Control — тариф BASIC, 1 год",
                    "metadata": {},
                }
            )
            mock_yk_class.return_value = mock_yk

            service = PaymentService(mock_session)

            payment, confirmation_url = await service.create_subscription_payment(
                user_id=1,
                tier_code="basic",
                period="yearly",
                return_url="https://example.com/success",
                customer_email="user@example.com",
            )

            assert payment.provider_payment_id == "yk-basic-yearly-new"
            assert payment.payment_metadata["tier_code"] == "basic"
            assert payment.payment_metadata["period"] == "yearly"

    @pytest.mark.asyncio
    async def test_same_tier_same_period_reuses_pending(self, mock_session):
        """User retries same BASIC monthly payment.

        Should reuse the existing pending payment.
        """
        existing = Payment(
            id=102,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-basic-monthly-existing",
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
            _make_result(_make_basic_tier()),
            _make_result(existing),
        ]

        with (
            patch("app.services.payment_service.get_settings") as mock_settings,
            patch("app.services.payment_service.YooKassaClient") as mock_yk_class,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings
            mock_yk_class.return_value = _make_succeeded_yookassa_mock()

            service = PaymentService(mock_session)

            payment, confirmation_url = await service.create_subscription_payment(
                user_id=1,
                tier_code="basic",
                period="monthly",
                return_url="https://example.com/success",
                customer_email="user@example.com",
            )

            assert payment.id == 102
            assert confirmation_url == "https://yookassa.ru/pay/existing"


class TestBackwardCompatibleSubscriptionPeriodKey:
    """Test that old payments with subscription_period key still work."""

    @pytest.mark.asyncio
    async def test_old_subscription_period_key_still_works(self, mock_session):
        """Old payment with subscription_period key should still activate correctly."""
        payment = Payment(
            id=90,
            user_id=1,
            provider="yookassa",
            provider_payment_id="yk-old-key",
            amount=Decimal("490"),
            currency="RUB",
            status=PaymentStatus.PENDING,
            payment_metadata={
                "tier_code": "basic",
                "subscription_period": "monthly",
                "user_id": "1",
            },
        )

        mock_session.execute.side_effect = [
            _make_result(payment),
            _make_result(_make_basic_tier()),
            _make_result(_make_user()),
        ]

        with (
            patch("app.services.payment_service.get_settings") as mock_settings,
            patch("app.services.payment_service.YooKassaClient") as mock_yk_class,
            patch("app.bot.main.create_bot") as mock_create_bot,
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "key"
            mock_settings.return_value = settings
            mock_yk_class.return_value = _make_succeeded_yookassa_mock()
            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock()
            mock_create_bot.return_value = mock_bot

            service = PaymentService(mock_session)

            mock_sub = MagicMock()
            mock_sub.id = 90
            mock_sub.expires_at = datetime.now(tz=UTC) + timedelta(days=30)
            service.subscription_service.create_subscription = AsyncMock(return_value=mock_sub)

            await service.handle_payment_success(
                {
                    "id": "yk-old-key",
                    "status": "succeeded",
                    "payment_method": {"type": "bank_card"},
                }
            )

            call_kwargs = service.subscription_service.create_subscription.call_args.kwargs
            assert call_kwargs["period"] == "monthly"
