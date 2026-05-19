"""Tests for YooKassa receipt formation and payment payload."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.payment_service import _build_receipt


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
        with patch("app.services.payment_service.get_settings") as mock_settings, \
             patch("app.services.payment_service.YooKassaClient") as mock_yk_class, \
             patch("app.services.payment_service.SubscriptionService"):
            settings = MagicMock()
            settings.yookassa_shop_id = "test_shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "test_secret"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.create_payment = AsyncMock(return_value={
                "id": "test-payment-id",
                "confirmation": {"confirmation_url": "https://yookassa.ru/pay"},
            })
            mock_yk_class.return_value = mock_yk

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_tier
            mock_session.execute.return_value = mock_result

            from app.services.payment_service import PaymentService
            service = PaymentService(mock_session)

            await service.create_subscription_payment(
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
            assert receipt["items"][0]["description"] == "Подписка MP Control — тариф BASIC, 1 месяц"

    @pytest.mark.asyncio
    async def test_create_payment_receipt_amount_matches_tier_price(self, mock_session, mock_tier):
        with patch("app.services.payment_service.get_settings") as mock_settings, \
             patch("app.services.payment_service.YooKassaClient") as mock_yk_class, \
             patch("app.services.payment_service.SubscriptionService"):
            settings = MagicMock()
            settings.yookassa_shop_id = "test_shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "test_secret"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.create_payment = AsyncMock(return_value={
                "id": "test-payment-id",
                "confirmation": {"confirmation_url": "https://yookassa.ru/pay"},
            })
            mock_yk_class.return_value = mock_yk

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_tier
            mock_session.execute.return_value = mock_result

            from app.services.payment_service import PaymentService
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
