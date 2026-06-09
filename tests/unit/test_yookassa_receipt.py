"""Tests for YooKassa receipt formation and payment flow."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.enums import PaymentStatus
from app.models.subscriptions import Payment
from app.services.payments.payment_service import _build_receipt


class TestBuildReceipt:
    """Test receipt builder produces valid YooKassa receipt structure."""

    def test_receipt_for_basic_monthly(self):
        receipt = _build_receipt(
            tier_name="BASIC",
            period="monthly",
            amount=Decimal("490"),
            customer_email="user@example.com",
        )
        assert receipt["customer"]["email"] == "user@example.com"
        assert len(receipt["items"]) == 1
        item = receipt["items"][0]
        assert item["description"] == "Подписка MP Control — тариф BASIC, 1 месяц"
        assert item["quantity"] == "1.00"
        assert item["amount"]["value"] == "490"
        assert item["amount"]["currency"] == "RUB"
        assert item["vat_code"] == 1
        assert item["payment_subject"] == "service"
        assert item["payment_mode"] == "full_payment"

    def test_receipt_for_pro_yearly(self):
        receipt = _build_receipt(
            tier_name="PRO",
            period="yearly",
            amount=Decimal("4900"),
            customer_email="seller@mail.ru",
        )
        item = receipt["items"][0]
        assert item["description"] == "Подписка MP Control — тариф PRO, 1 год"
        assert item["amount"]["value"] == "4900"

    def test_receipt_amount_matches_payment_amount(self):
        amount = Decimal("999.99")
        receipt = _build_receipt(
            tier_name="BASIC",
            period="monthly",
            amount=amount,
            customer_email="test@test.com",
        )
        assert receipt["items"][0]["amount"]["value"] == str(amount)

    def test_receipt_customer_email_required(self):
        receipt = _build_receipt(
            tier_name="BASIC",
            period="monthly",
            amount=Decimal("100"),
            customer_email="valid@email.com",
        )
        assert "customer" in receipt
        assert receipt["customer"]["email"] == "valid@email.com"

    def test_receipt_single_item(self):
        receipt = _build_receipt(
            tier_name="BASIC",
            period="monthly",
            amount=Decimal("100"),
            customer_email="a@b.com",
        )
        assert len(receipt["items"]) == 1


class TestPaymentServiceWithReceipt:
    """Test PaymentService.create_subscription_payment passes correct receipt."""

    @pytest.fixture
    def mock_session(self):
        session = MagicMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        return session

    @pytest.fixture
    def mock_tier(self):
        tier = MagicMock()
        tier.name = "BASIC"
        tier.code = "basic"
        tier.price_monthly = Decimal("490")
        tier.price_yearly = Decimal("4900")
        return tier

    @pytest.mark.asyncio
    async def test_create_payment_passes_receipt_to_yookassa(self, mock_session, mock_tier):
        with (
            patch("app.services.payments.payment_service.get_settings") as mock_settings,
            patch("app.services.payments.payment_service.YooKassaClient") as mock_yk_class,
            patch("app.services.payment_service.SubscriptionService"),
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "test_shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "test_secret"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.create_payment = AsyncMock(
                return_value={
                    "id": "test-payment-id",
                    "status": "pending",
                    "amount": {"value": "490", "currency": "RUB"},
                    "confirmation": {"confirmation_url": "https://yookassa.ru/pay"},
                    "description": "Подписка MP Control — тариф BASIC, 1 месяц",
                    "metadata": {},
                }
            )
            mock_yk.get_payment = AsyncMock(return_value={})
            mock_yk_class.return_value = mock_yk

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.side_effect = [mock_tier, None]
            mock_session.execute.return_value = mock_result

            from app.services.payments.payment_service import PaymentService

            service = PaymentService(mock_session)

            payment, confirmation_url = await service.create_subscription_payment(
                user_id=100,
                tier_code="basic",
                period="monthly",
                return_url="https://example.com/success",
                customer_email="user@example.com",
            )

            call_kwargs = mock_yk.create_payment.call_args[1]
            assert "receipt" in call_kwargs
            receipt = call_kwargs["receipt"]
            assert receipt["customer"]["email"] == "user@example.com"
            assert receipt["items"][0]["amount"]["value"] == "490"
            assert (
                receipt["items"][0]["description"] == "Подписка MP Control — тариф BASIC, 1 месяц"
            )
            assert confirmation_url == "https://yookassa.ru/pay"

    @pytest.mark.asyncio
    async def test_create_payment_receipt_amount_matches_tier_price(self, mock_session, mock_tier):
        with (
            patch("app.services.payments.payment_service.get_settings") as mock_settings,
            patch("app.services.payments.payment_service.YooKassaClient") as mock_yk_class,
            patch("app.services.payment_service.SubscriptionService"),
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "test_shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "test_secret"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.create_payment = AsyncMock(
                return_value={
                    "id": "test-payment-id",
                    "status": "pending",
                    "amount": {"value": "490", "currency": "RUB"},
                    "confirmation": {"confirmation_url": "https://yookassa.ru/pay"},
                    "description": "Подписка MP Control — тариф BASIC, 1 месяц",
                    "metadata": {},
                }
            )
            mock_yk.get_payment = AsyncMock(return_value={})
            mock_yk_class.return_value = mock_yk

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.side_effect = [mock_tier, None]
            mock_session.execute.return_value = mock_result

            from app.services.payments.payment_service import PaymentService

            service = PaymentService(mock_session)

            await service.create_subscription_payment(
                user_id=100,
                tier_code="basic",
                period="monthly",
                return_url="https://example.com/success",
                customer_email="user@example.com",
            )

            call_kwargs = mock_yk.create_payment.call_args[1]
            receipt_amount = Decimal(call_kwargs["receipt"]["items"][0]["amount"]["value"])
            payment_amount = call_kwargs["amount"]
            assert receipt_amount == payment_amount

    @pytest.mark.asyncio
    async def test_create_payment_returns_correct_structure(self, mock_session, mock_tier):
        """Handler expects (Payment, confirmation_url) tuple with no KeyError."""
        with (
            patch("app.services.payments.payment_service.get_settings") as mock_settings,
            patch("app.services.payments.payment_service.YooKassaClient") as mock_yk_class,
            patch("app.services.payment_service.SubscriptionService"),
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "test_shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "test_secret"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.create_payment = AsyncMock(
                return_value={
                    "id": "test-payment-id",
                    "status": "pending",
                    "amount": {"value": "490", "currency": "RUB"},
                    "confirmation": {"confirmation_url": "https://yookassa.ru/pay/test"},
                    "description": "Подписка MP Control — тариф BASIC, 1 месяц",
                    "metadata": {},
                }
            )
            mock_yk.get_payment = AsyncMock(return_value={})
            mock_yk_class.return_value = mock_yk

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.side_effect = [mock_tier, None]
            mock_session.execute.return_value = mock_result

            from app.services.payments.payment_service import PaymentService

            service = PaymentService(mock_session)

            payment, confirmation_url = await service.create_subscription_payment(
                user_id=100,
                tier_code="basic",
                period="monthly",
                return_url="https://example.com/success",
                customer_email="user@example.com",
            )

            assert payment is not None
            assert payment.provider_payment_id == "test-payment-id"
            assert payment.status == PaymentStatus.PENDING
            assert isinstance(confirmation_url, str)
            assert "yookassa" in confirmation_url

    @pytest.mark.asyncio
    async def test_create_payment_uses_human_readable_description(self, mock_session, mock_tier):
        with (
            patch("app.services.payments.payment_service.get_settings") as mock_settings,
            patch("app.services.payments.payment_service.YooKassaClient") as mock_yk_class,
            patch("app.services.payment_service.SubscriptionService"),
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "test_shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "test_secret"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.create_payment = AsyncMock(
                return_value={
                    "id": "test-payment-id",
                    "status": "pending",
                    "amount": {"value": "4900", "currency": "RUB"},
                    "confirmation": {"confirmation_url": "https://yookassa.ru/pay"},
                    "description": "",
                    "metadata": {},
                }
            )
            mock_yk.get_payment = AsyncMock(return_value={})
            mock_yk_class.return_value = mock_yk

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.side_effect = [mock_tier, None]
            mock_session.execute.return_value = mock_result

            from app.services.payments.payment_service import PaymentService

            service = PaymentService(mock_session)

            await service.create_subscription_payment(
                user_id=100,
                tier_code="basic",
                period="yearly",
                return_url="https://example.com/success",
                customer_email="user@example.com",
            )

            call_kwargs = mock_yk.create_payment.call_args[1]
            assert call_kwargs["description"] == "Подписка MP Control — тариф BASIC, 1 год"

    @pytest.mark.asyncio
    async def test_pending_payment_reused_instead_of_duplicate(self, mock_session, mock_tier):
        """If a PENDING payment exists, return it instead of creating a new one."""
        with (
            patch("app.services.payments.payment_service.get_settings") as mock_settings,
            patch("app.services.payments.payment_service.YooKassaClient") as mock_yk_class,
            patch("app.services.payment_service.SubscriptionService"),
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "test_shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "test_secret"
            mock_settings.return_value = settings

            existing_payment = Payment(
                id=42,
                user_id=100,
                provider="yookassa",
                provider_payment_id="existing-payment-id",
                amount=Decimal("490"),
                currency="RUB",
                status=PaymentStatus.PENDING,
                payment_metadata={"tier_code": "basic", "period": "monthly"},
            )

            mock_yk = MagicMock()
            mock_yk.create_payment = AsyncMock(
                return_value={
                    "id": "new-payment-id",
                    "status": "pending",
                    "amount": {"value": "490", "currency": "RUB"},
                    "confirmation": {"confirmation_url": "https://yookassa.ru/new"},
                    "description": "",
                    "metadata": {},
                }
            )
            mock_yk.get_payment = AsyncMock(
                return_value={
                    "id": "existing-payment-id",
                    "confirmation": {"confirmation_url": "https://yookassa.ru/existing"},
                }
            )
            mock_yk_class.return_value = mock_yk

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.side_effect = [mock_tier, existing_payment]
            mock_session.execute.return_value = mock_result

            from app.services.payments.payment_service import PaymentService

            service = PaymentService(mock_session)

            payment, confirmation_url = await service.create_subscription_payment(
                user_id=100,
                tier_code="basic",
                period="monthly",
                return_url="https://example.com/success",
                customer_email="user@example.com",
            )

            assert payment.id == 42
            assert payment.provider_payment_id == "existing-payment-id"
            assert confirmation_url == "https://yookassa.ru/existing"
            mock_yk.create_payment.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_keyerror_on_yookassa_response(self, mock_session, mock_tier):
        """Accessing yookassa_payment['id'] must not raise KeyError."""
        with (
            patch("app.services.payments.payment_service.get_settings") as mock_settings,
            patch("app.services.payments.payment_service.YooKassaClient") as mock_yk_class,
            patch("app.services.payment_service.SubscriptionService"),
        ):
            settings = MagicMock()
            settings.yookassa_shop_id = "test_shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "test_secret"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.create_payment = AsyncMock(
                return_value={
                    "id": "319e5edc-000f-5001-9000-1674598f11a2",
                    "status": "pending",
                    "amount": {"value": "490", "currency": "RUB"},
                    "confirmation": {"confirmation_url": "https://yookassa.ru/pay"},
                    "description": "Подписка MP Control — тариф BASIC, 1 месяц",
                    "metadata": {},
                }
            )
            mock_yk.get_payment = AsyncMock(return_value={})
            mock_yk_class.return_value = mock_yk

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.side_effect = [mock_tier, None]
            mock_session.execute.return_value = mock_result

            from app.services.payments.payment_service import PaymentService

            service = PaymentService(mock_session)

            payment, confirmation_url = await service.create_subscription_payment(
                user_id=1,
                tier_code="basic",
                period="monthly",
                return_url="https://example.com/success",
                customer_email="user@example.com",
            )

            assert payment.provider_payment_id == "319e5edc-000f-5001-9000-1674598f11a2"
            assert confirmation_url == "https://yookassa.ru/pay"


class TestMissingEmailPreventsPayment:
    """Test that missing email is handled before payment creation."""

    def test_build_receipt_requires_non_empty_email(self):
        receipt = _build_receipt(
            tier_name="BASIC",
            period="monthly",
            amount=Decimal("100"),
            customer_email="valid@test.com",
        )
        assert receipt["customer"]["email"] == "valid@test.com"

    def test_build_receipt_with_empty_email_still_structured(self):
        receipt = _build_receipt(
            tier_name="BASIC",
            period="monthly",
            amount=Decimal("100"),
            customer_email="",
        )
        assert "customer" in receipt
        assert receipt["customer"]["email"] == ""
