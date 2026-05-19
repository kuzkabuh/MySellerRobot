"""Tests for payment success notification, receipt handling, and idempotency."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.enums import PaymentStatus
from app.models.subscriptions import Payment, SubscriptionTier


class TestPaymentSuccessNotification:
    """Test post-payment success notification."""

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
        tier.name = "PRO"
        tier.code = "pro"
        tier.price_monthly = Decimal("1490")
        tier.price_yearly = Decimal("14900")
        tier.feature_web_cabinet = True
        tier.feature_analytics = True
        tier.feature_plan_fact = True
        tier.feature_break_even = True
        tier.feature_stock_forecast = True
        tier.feature_alerts = True
        tier.feature_priority_support = False
        tier.feature_api_access = False
        return tier

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = 100
        user.telegram_id = 123456789
        user.timezone = "Europe/Moscow"
        user.payment_email = "user@example.com"
        return user

    @pytest.fixture
    def mock_subscription(self):
        sub = MagicMock()
        sub.id = 1
        sub.expires_at = datetime(2026, 6, 19, tzinfo=UTC)
        sub.tier_id = 2
        return sub

    @pytest.fixture
    def mock_payment(self):
        payment = MagicMock()
        payment.id = 42
        payment.user_id = 100
        payment.provider_payment_id = "test-yk-payment-id"
        payment.amount = Decimal("1490")
        payment.currency = "RUB"
        payment.status = PaymentStatus.SUCCEEDED
        payment.paid_at = datetime(2026, 5, 19, 17, 14, tzinfo=UTC)
        payment.success_notification_sent_at = None
        payment.receipt_id = None
        payment.receipt_status = None
        payment.payment_metadata = {
            "tier_code": "pro",
            "period": "monthly",
            "user_id": "100",
        }
        return payment

    @pytest.mark.asyncio
    async def test_first_payment_sends_notification(self, mock_session, mock_tier, mock_user, mock_subscription, mock_payment):
        """First successful payment should send notification."""
        with patch("app.services.payment_service.get_settings") as mock_settings, \
             patch("app.services.payment_service.YooKassaClient") as mock_yk_class, \
             patch("app.services.payment_service.SubscriptionService"):
            settings = MagicMock()
            settings.yookassa_shop_id = "test_shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "test_secret"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.create_payment = AsyncMock(return_value={})
            mock_yk.get_payment = AsyncMock(return_value={})
            mock_yk_class.return_value = mock_yk

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.side_effect = [mock_tier, None]
            mock_session.execute.return_value = mock_result

            from app.services.payment_service import PaymentService
            service = PaymentService(mock_session)

            with patch("app.bot.main.create_bot") as mock_create_bot:
                mock_bot = MagicMock()
                mock_bot.send_message = AsyncMock()
                mock_create_bot.return_value = mock_bot

                user_result = MagicMock()
                user_result.scalar_one_or_none.return_value = mock_user

                async def mock_execute(stmt):
                    if "User" in str(stmt) or "users" in str(stmt):
                        return user_result
                    return mock_result

                mock_session.execute = AsyncMock(side_effect=mock_execute)

                await service._send_payment_success_notification(
                    payment=mock_payment,
                    subscription=mock_subscription,
                    tier_code="pro",
                    period="monthly",
                )

                mock_bot.send_message.assert_called_once()
                call_args = mock_bot.send_message.call_args
                assert call_args[0][0] == 123456789
                text = call_args[0][1]
                assert "Оплата получена" in text
                assert "PRO" in text
                assert "1490" in text
                assert "Активна" in text
                assert "Web-кабинет" in text

    @pytest.mark.asyncio
    async def test_duplicate_notification_skipped(self, mock_session, mock_payment):
        """If success_notification_sent_at is set, notification should be skipped."""
        mock_payment.success_notification_sent_at = datetime.now(tz=UTC)

        from app.services.payment_service import PaymentService
        service = PaymentService(mock_session)

        with patch("app.bot.main.create_bot") as mock_create_bot:
            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock()
            mock_create_bot.return_value = mock_bot

            await service._send_payment_success_notification(
                payment=mock_payment,
                subscription=MagicMock(),
                tier_code="pro",
                period="monthly",
            )

            mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_notification_sets_timestamp(self, mock_session, mock_tier, mock_user, mock_subscription, mock_payment):
        """After successful notification, success_notification_sent_at should be set."""
        with patch("app.services.payment_service.get_settings") as mock_settings, \
             patch("app.services.payment_service.YooKassaClient") as mock_yk_class, \
             patch("app.services.payment_service.SubscriptionService"):
            settings = MagicMock()
            settings.yookassa_shop_id = "test_shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "test_secret"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.create_payment = AsyncMock(return_value={})
            mock_yk.get_payment = AsyncMock(return_value={})
            mock_yk_class.return_value = mock_yk

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_tier
            mock_session.execute.return_value = mock_result

            from app.services.payment_service import PaymentService
            service = PaymentService(mock_session)

            with patch("app.bot.main.create_bot") as mock_create_bot:
                mock_bot = MagicMock()
                mock_bot.send_message = AsyncMock()
                mock_create_bot.return_value = mock_bot

                user_result = MagicMock()
                user_result.scalar_one_or_none.return_value = mock_user

                async def mock_execute(stmt):
                    if "User" in str(stmt) or "users" in str(stmt):
                        return user_result
                    return mock_result

                mock_session.execute = AsyncMock(side_effect=mock_execute)

                await service._send_payment_success_notification(
                    payment=mock_payment,
                    subscription=mock_subscription,
                    tier_code="pro",
                    period="monthly",
                )

                assert mock_payment.success_notification_sent_at is not None


class TestReceiptTracking:
    """Test receipt info extraction and status tracking."""

    @pytest.fixture
    def mock_session(self):
        session = MagicMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_save_receipt_info_from_yookassa_response(self, mock_session):
        """Receipt info should be extracted and saved from YooKassa response."""
        payment = MagicMock()
        payment.id = 42
        payment.receipt_id = None
        payment.receipt_status = None

        yookassa_data = {
            "id": "test-payment-id",
            "status": "succeeded",
            "receipt": {
                "id": "receipt-123",
                "status": "succeeded",
                "registration_status": "succeeded",
            },
        }

        from app.services.payment_service import PaymentService
        service = PaymentService(mock_session)

        await service._save_receipt_info(payment, yookassa_data)

        assert payment.receipt_id == "receipt-123"
        assert payment.receipt_status == "succeeded"

    @pytest.mark.asyncio
    async def test_save_receipt_info_no_receipt_data(self, mock_session):
        """If no receipt data in response, nothing should be saved."""
        payment = MagicMock()
        payment.id = 42
        payment.receipt_id = None
        payment.receipt_status = None

        yookassa_data = {
            "id": "test-payment-id",
            "status": "succeeded",
        }

        from app.services.payment_service import PaymentService
        service = PaymentService(mock_session)

        await service._save_receipt_info(payment, yookassa_data)

        assert payment.receipt_id is None
        assert payment.receipt_status is None

    @pytest.mark.asyncio
    async def test_fetch_receipt_status_from_api(self, mock_session):
        """Receipt status should be fetched from YooKassa API if receipt_id is known."""
        payment = MagicMock()
        payment.id = 42
        payment.provider_payment_id = "test-payment-id"
        payment.receipt_id = "receipt-123"
        payment.receipt_status = "pending"

        with patch("app.services.payment_service.get_settings") as mock_settings, \
             patch("app.services.payment_service.YooKassaClient") as mock_yk_class, \
             patch("app.services.payment_service.SubscriptionService"):
            settings = MagicMock()
            settings.yookassa_shop_id = "test_shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "test_secret"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk.get_payment = AsyncMock(return_value={
                "id": "test-payment-id",
                "status": "succeeded",
                "receipt": {
                    "id": "receipt-123",
                    "status": "succeeded",
                },
            })
            mock_yk_class.return_value = mock_yk

            from app.services.payment_service import PaymentService
            service = PaymentService(mock_session)

            status = await service._fetch_receipt_status(payment)

            assert status == "succeeded"
            assert payment.receipt_status == "succeeded"


class TestReceiptKeyboard:
    """Test payment success keyboard structure."""

    def test_payment_success_keyboard_has_correct_buttons(self):
        """Keyboard should have subscription, receipt, and main menu buttons."""
        from app.services.payment_service import PaymentService

        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_session.flush = AsyncMock()

        with patch("app.services.payment_service.get_settings") as mock_settings, \
             patch("app.services.payment_service.YooKassaClient") as mock_yk_class, \
             patch("app.services.payment_service.SubscriptionService"):
            settings = MagicMock()
            settings.yookassa_shop_id = "test_shop"
            settings.yookassa_secret_key.get_secret_value.return_value = "test_secret"
            mock_settings.return_value = settings

            mock_yk = MagicMock()
            mock_yk_class.return_value = mock_yk

            service = PaymentService(mock_session)
            keyboard = service._build_payment_success_keyboard(payment_id=42)

            assert len(keyboard.inline_keyboard) == 3

            sub_btn = keyboard.inline_keyboard[0][0]
            assert sub_btn.text == "💳 Моя подписка"
            assert sub_btn.callback_data == "subscription:current"

            receipt_btn = keyboard.inline_keyboard[1][0]
            assert receipt_btn.text == "🧾 Чек по платежу"
            assert receipt_btn.callback_data == "subscription:receipt:42"

            menu_btn = keyboard.inline_keyboard[2][0]
            assert menu_btn.text == "🏠 Главное меню"
            assert menu_btn.callback_data == "back_main"


class TestMaskEmail:
    """Test email masking for receipt display."""

    def test_mask_email_standard(self):
        from app.bot.handlers.subscription import _mask_email
        assert _mask_email("user@example.com") == "u***r@example.com"

    def test_mask_email_short(self):
        from app.bot.handlers.subscription import _mask_email
        assert _mask_email("ab@example.com") == "a***@example.com"

    def test_mask_email_single_char(self):
        from app.bot.handlers.subscription import _mask_email
        result = _mask_email("a@example.com")
        assert result == "a***@example.com"

    def test_mask_email_empty(self):
        from app.bot.handlers.subscription import _mask_email
        assert _mask_email("") == ""

    def test_mask_email_no_at(self):
        from app.bot.handlers.subscription import _mask_email
        assert _mask_email("invalid") == "invalid"
