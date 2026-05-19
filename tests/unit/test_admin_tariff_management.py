"""version: 1.1.0
description: Tests for admin tariff management in subscription service.
updated: 2026-05-17
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.enums import SubscriptionStatus
from app.models.subscriptions import SubscriptionTier, UserSubscription
from app.services.subscription_service import SubscriptionService


def _make_tier(
    code: str = "pro",
    name: str = "PRO",
    price_monthly: Decimal = Decimal("1490"),
    price_yearly: Decimal | None = Decimal("14900"),
    max_mp: int = 5,
    max_orders: int | None = None,
    max_products: int | None = None,
) -> SubscriptionTier:
    return SubscriptionTier(
        id=1,
        code=code,
        name=name,
        description=f"Description for {name}",
        price_monthly=price_monthly,
        price_yearly=price_yearly,
        max_marketplace_accounts=max_mp,
        max_orders_per_month=max_orders,
        max_products=max_products,
        feature_web_cabinet=True,
        feature_analytics=True,
        feature_plan_fact=True,
        feature_break_even=True,
        feature_stock_forecast=True,
        feature_alerts=True,
        feature_priority_support=True,
        feature_api_access=False,
        is_active=True,
        sort_order=0,
    )


def _make_user_subscription(
    user_id: int = 1,
    tier_id: int = 1,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    expires_at: datetime | None = None,
    is_trial: bool = False,
) -> UserSubscription:
    return UserSubscription(
        id=1,
        user_id=user_id,
        tier_id=tier_id,
        status=status,
        started_at=datetime.now(tz=UTC),
        expires_at=expires_at,
        is_trial=is_trial,
        trial_ends_at=None,
        payment_provider="yookassa",
        payment_id="test-payment-id",
        auto_renew=True,
    )


class TestAssignAdminSubscription:
    @pytest.mark.asyncio
    async def test_assign_pro_30_days(self) -> None:
        """Test assigning PRO tariff for 30 days."""
        session = AsyncMock()
        session.get = AsyncMock()
        session.execute = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()

        tier = _make_tier(code="pro", name="PRO")
        service = SubscriptionService(session)

        # Mock get_tier_by_code
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=tier)
        session.execute.return_value = mock_result

        # Mock get_active_subscription - no active subscription
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none = MagicMock(return_value=None)
        session.execute.side_effect = [mock_result, mock_result2]

        # Mock user lookup
        mock_user = MagicMock()
        mock_user.id = 1
        session.get.return_value = mock_user

        subscription = await service.assign_admin_subscription(
            user_id=1,
            tier_code="pro",
            days=30,
            admin_user_id=999,
        )

        assert subscription is not None
        assert subscription.user_id == 1
        assert subscription.tier_id == tier.id
        assert subscription.status == SubscriptionStatus.ACTIVE
        assert subscription.payment_provider == "admin_manual"
        assert subscription.expires_at is not None
        assert subscription.is_trial is False
        assert subscription.created_at is not None
        assert subscription.updated_at is not None

    @pytest.mark.asyncio
    async def test_assign_free_cancels_active(self) -> None:
        """Test assigning FREE tariff cancels active subscription."""
        session = AsyncMock()
        session.execute = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.refresh = AsyncMock()

        free_tier = _make_tier(
            code="free",
            name="FREE",
            price_monthly=Decimal("0"),
            price_yearly=Decimal("0"),
        )
        old_tier = _make_tier(
            code="basic",
            name="BASIC",
            price_monthly=Decimal("490"),
            price_yearly=Decimal("4900"),
        )
        active_sub = _make_user_subscription(user_id=1, tier_id=2)
        active_sub.tier = old_tier

        service = SubscriptionService(session)

        # Mock get_tier_by_code returns free tier
        mock_result_free = MagicMock()
        mock_result_free.scalar_one_or_none = MagicMock(return_value=free_tier)

        # Mock get_active_subscription returns active subscription
        mock_result_active = MagicMock()
        mock_result_active.scalar_one_or_none = MagicMock(return_value=active_sub)

        # Order: get_tier_by_code, get_active_subscription
        session.execute.side_effect = [mock_result_free, mock_result_active]

        # Mock session.get to return user for User lookup, and active_sub for subscription lookup
        async def mock_get(model, id_):
            if model.__name__ == "User":
                mock_user = MagicMock()
                mock_user.id = 1
                return mock_user
            elif model.__name__ == "UserSubscription":
                return active_sub
            return None

        session.get = mock_get

        result = await service.assign_admin_subscription(
            user_id=1,
            tier_code="free",
            days=None,
            admin_user_id=999,
        )

        # FREE tier should return None (no subscription created)
        assert result is None
        # Active subscription should have been cancelled
        assert active_sub.status == SubscriptionStatus.CANCELLED
        assert active_sub.auto_renew is False

    @pytest.mark.asyncio
    async def test_assign_enterprise_indefinite(self) -> None:
        """Test assigning ENTERPRISE tariff with no expiration."""
        session = AsyncMock()
        session.get = AsyncMock()
        session.execute = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()

        tier = _make_tier(
            code="enterprise",
            name="ENTERPRISE",
            price_monthly=Decimal("0"),
            price_yearly=Decimal("0"),
            max_mp=999,
            max_orders=None,
            max_products=None,
        )
        service = SubscriptionService(session)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=tier)
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none = MagicMock(return_value=None)
        session.execute.side_effect = [mock_result, mock_result2]

        mock_user = MagicMock()
        mock_user.id = 1
        session.get.return_value = mock_user

        subscription = await service.assign_admin_subscription(
            user_id=1,
            tier_code="enterprise",
            days=None,
            admin_user_id=999,
        )

        assert subscription is not None
        assert subscription.expires_at is None
        assert subscription.created_at is not None
        assert subscription.updated_at is not None

    @pytest.mark.asyncio
    async def test_assign_raises_for_unknown_tier(self) -> None:
        """Test that assigning unknown tier raises ValueError."""
        session = AsyncMock()
        session.execute = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute.return_value = mock_result

        service = SubscriptionService(session)

        with pytest.raises(ValueError, match="Tier unknown not found"):
            await service.assign_admin_subscription(
                user_id=1,
                tier_code="unknown",
                days=30,
                admin_user_id=999,
            )

    @pytest.mark.asyncio
    async def test_assign_raises_for_unknown_user(self) -> None:
        """Test that assigning to unknown user raises ValueError."""
        session = AsyncMock()
        session.get = AsyncMock()
        session.execute = AsyncMock()

        tier = _make_tier()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=tier)
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none = MagicMock(return_value=None)
        session.execute.side_effect = [mock_result, mock_result2]
        session.get.return_value = None

        service = SubscriptionService(session)

        with pytest.raises(ValueError, match="User 999 not found"):
            await service.assign_admin_subscription(
                user_id=999,
                tier_code="pro",
                days=30,
                admin_user_id=1,
            )

    @pytest.mark.asyncio
    async def test_assign_basic_365_days(self) -> None:
        """Test assigning BASIC tariff for 365 days."""
        session = AsyncMock()
        session.get = AsyncMock()
        session.execute = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()

        tier = _make_tier(
            code="basic",
            name="BASIC",
            price_monthly=Decimal("490"),
            price_yearly=Decimal("4900"),
            max_mp=2,
            max_orders=1000,
            max_products=1000,
        )
        service = SubscriptionService(session)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=tier)
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none = MagicMock(return_value=None)
        session.execute.side_effect = [mock_result, mock_result2]

        mock_user = MagicMock()
        mock_user.id = 1
        session.get.return_value = mock_user

        subscription = await service.assign_admin_subscription(
            user_id=1,
            tier_code="basic",
            days=365,
            admin_user_id=999,
        )

        assert subscription is not None
        assert subscription.expires_at is not None
        assert subscription.created_at is not None
        assert subscription.updated_at is not None
        # Should be approximately 365 days from now
        delta = subscription.expires_at - datetime.now(tz=UTC)
        assert 360 <= delta.days <= 370

    @pytest.mark.asyncio
    async def test_admin_assign_pro_365_days_has_timestamps(self) -> None:
        """Test assigning PRO tariff for 365 days fills timestamps."""
        session = AsyncMock()
        session.get = AsyncMock()
        session.execute = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()

        tier = _make_tier(code="pro", name="PRO")
        service = SubscriptionService(session)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=tier)
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none = MagicMock(return_value=None)
        session.execute.side_effect = [mock_result, mock_result2]

        mock_user = MagicMock()
        mock_user.id = 1
        session.get.return_value = mock_user

        subscription = await service.assign_admin_subscription(
            user_id=1,
            tier_code="pro",
            days=365,
            admin_user_id=999,
        )

        assert subscription is not None
        assert subscription.created_at is not None
        assert subscription.updated_at is not None
        assert subscription.expires_at is not None
        delta = subscription.expires_at - datetime.now(tz=UTC)
        assert 360 <= delta.days <= 370


class TestAdminTariffAssignHandler:
    """Test the Telegram bot handler for admin tariff assignment."""

    def _make_callback(self, data: str, msg: MagicMock, bot=None):
        """Create a mock callback that satisfies the handler's expectations."""
        callback = MagicMock()
        callback.data = data
        callback.from_user = MagicMock(id=100, first_name="Admin")
        callback.message = msg
        callback.answer = AsyncMock()
        callback.bot = bot
        return callback

    def _mock_settings(self):
        """Mock settings with admin_ids containing 100."""
        settings = MagicMock()
        settings.admin_ids = {100}
        return settings

    @pytest.mark.asyncio
    async def test_assign_handler_uses_target_user_timezone(self) -> None:
        """Handler should use target user timezone, not crash with UnboundLocalError."""
        from app.bot.handlers.subscription import admin_tariff_assign_handler

        msg = MagicMock()
        msg.edit_text = AsyncMock()
        callback = self._make_callback(
            data="admin_tariff:assign:pro:30:200",
            msg=msg,
            bot=MagicMock(send_message=AsyncMock()),
        )

        mock_admin_user = MagicMock()
        mock_admin_user.id = 10
        mock_admin_user.telegram_id = 100
        mock_admin_user.first_name = "Admin"
        mock_admin_user.timezone = "Europe/Moscow"

        mock_target_user = MagicMock()
        mock_target_user.id = 20
        mock_target_user.telegram_id = 200
        mock_target_user.first_name = "TargetUser"
        mock_target_user.timezone = "Asia/Yekaterinburg"

        mock_tier = MagicMock()
        mock_tier.id = 2
        mock_tier.code = "pro"
        mock_tier.name = "PRO"

        mock_subscription = MagicMock()
        mock_subscription.id = 50
        mock_subscription.expires_at = datetime(2026, 6, 19, tzinfo=UTC)
        mock_subscription.tier_id = 2
        mock_subscription.tier = mock_tier

        class FakeUserRepo:
            def __init__(self, session):
                self._map = {100: mock_admin_user, 200: mock_target_user}

            async def get_by_telegram_id(self, telegram_id: int):
                return self._map.get(telegram_id)

        class FakeSubService:
            def __init__(self, session):
                self.session = session

            async def get_tier_by_code(self, code: str):
                return mock_tier if code == "pro" else None

            async def assign_admin_subscription(self, **kwargs):
                return mock_subscription

        class FakeSessionFactory:
            def __init__(self):
                self.session = MagicMock()
                self.session.commit = AsyncMock()

            async def __aenter__(self):
                return self.session

            async def __aexit__(self, *args):
                pass

        with patch(
            "app.bot.handlers.subscription.UserRepository",
            FakeUserRepo,
        ), patch(
            "app.bot.handlers.subscription.SubscriptionService",
            FakeSubService,
        ), patch(
            "app.bot.handlers.subscription.AsyncSessionFactory",
            FakeSessionFactory,
        ), patch(
            "app.bot.handlers.subscription.get_settings",
            return_value=self._mock_settings(),
        ), patch(
            "app.bot.handlers.subscription._callback_message",
            return_value=msg,
        ):
            await admin_tariff_assign_handler(callback)

        msg.edit_text.assert_called_once()
        call_args = msg.edit_text.call_args
        text = call_args[0][0]
        assert "PRO" in text
        assert "TargetUser" in text
        assert "19.06.2026" in text
        callback.answer.assert_called()

    @pytest.mark.asyncio
    async def test_assign_handler_self_assignment(self) -> None:
        """Handler should work when admin assigns to themselves."""
        from app.bot.handlers.subscription import admin_tariff_assign_handler

        msg = MagicMock()
        msg.edit_text = AsyncMock()
        callback = self._make_callback(
            data="admin_tariff:assign:basic:30",
            msg=msg,
            bot=MagicMock(send_message=AsyncMock()),
        )

        mock_admin_user = MagicMock()
        mock_admin_user.id = 10
        mock_admin_user.telegram_id = 100
        mock_admin_user.first_name = "Admin"
        mock_admin_user.timezone = "Europe/Moscow"

        mock_tier = MagicMock()
        mock_tier.id = 1
        mock_tier.code = "basic"
        mock_tier.name = "BASIC"

        mock_subscription = MagicMock()
        mock_subscription.id = 51
        mock_subscription.expires_at = datetime(2026, 6, 19, tzinfo=UTC)

        class FakeUserRepo:
            def __init__(self, session):
                self.session = session

            async def get_by_telegram_id(self, telegram_id: int):
                return mock_admin_user

        class FakeSubService:
            def __init__(self, session):
                self.session = session

            async def get_tier_by_code(self, code: str):
                return mock_tier

            async def assign_admin_subscription(self, **kwargs):
                return mock_subscription

        class FakeSessionFactory:
            def __init__(self):
                self.session = MagicMock()
                self.session.commit = AsyncMock()

            async def __aenter__(self):
                return self.session

            async def __aexit__(self, *args):
                pass

        with patch(
            "app.bot.handlers.subscription.UserRepository",
            FakeUserRepo,
        ), patch(
            "app.bot.handlers.subscription.SubscriptionService",
            FakeSubService,
        ), patch(
            "app.bot.handlers.subscription.AsyncSessionFactory",
            FakeSessionFactory,
        ), patch(
            "app.bot.handlers.subscription.get_settings",
            return_value=self._mock_settings(),
        ), patch(
            "app.bot.handlers.subscription._callback_message",
            return_value=msg,
        ):
            await admin_tariff_assign_handler(callback)

        msg.edit_text.assert_called_once()
        call_args = msg.edit_text.call_args
        text = call_args[0][0]
        assert "BASIC" in text
        assert "Admin" in text
        callback.answer.assert_called()

    @pytest.mark.asyncio
    async def test_assign_handler_fallback_timezone(self) -> None:
        """Handler should use fallback timezone if target user has no timezone."""
        from app.bot.handlers.subscription import admin_tariff_assign_handler

        msg = MagicMock()
        msg.edit_text = AsyncMock()
        callback = self._make_callback(
            data="admin_tariff:assign:pro:30:200",
            msg=msg,
            bot=MagicMock(send_message=AsyncMock()),
        )

        mock_admin_user = MagicMock()
        mock_admin_user.id = 10
        mock_admin_user.telegram_id = 100
        mock_admin_user.first_name = "Admin"
        mock_admin_user.timezone = "Europe/Moscow"

        mock_target_user = MagicMock()
        mock_target_user.id = 20
        mock_target_user.telegram_id = 200
        mock_target_user.first_name = "NoTZ"
        mock_target_user.timezone = None

        mock_tier = MagicMock()
        mock_tier.id = 2
        mock_tier.code = "pro"
        mock_tier.name = "PRO"

        mock_subscription = MagicMock()
        mock_subscription.id = 52
        mock_subscription.expires_at = datetime(2026, 6, 19, tzinfo=UTC)

        class FakeUserRepo:
            def __init__(self, session):
                self._map = {100: mock_admin_user, 200: mock_target_user}

            async def get_by_telegram_id(self, telegram_id: int):
                return self._map.get(telegram_id)

        class FakeSubService:
            def __init__(self, session):
                self.session = session

            async def get_tier_by_code(self, code: str):
                return mock_tier

            async def assign_admin_subscription(self, **kwargs):
                return mock_subscription

        class FakeSessionFactory:
            def __init__(self):
                self.session = MagicMock()
                self.session.commit = AsyncMock()

            async def __aenter__(self):
                return self.session

            async def __aexit__(self, *args):
                pass

        with patch(
            "app.bot.handlers.subscription.UserRepository",
            FakeUserRepo,
        ), patch(
            "app.bot.handlers.subscription.SubscriptionService",
            FakeSubService,
        ), patch(
            "app.bot.handlers.subscription.AsyncSessionFactory",
            FakeSessionFactory,
        ), patch(
            "app.bot.handlers.subscription.get_settings",
            return_value=self._mock_settings(),
        ), patch(
            "app.bot.handlers.subscription._callback_message",
            return_value=msg,
        ):
            await admin_tariff_assign_handler(callback)

        msg.edit_text.assert_called_once()
        callback.answer.assert_called()

    @pytest.mark.asyncio
    async def test_assign_handler_service_error_no_duplicate(self) -> None:
        """If service fails, admin sees error. No duplicate subscription created."""
        from app.bot.handlers.subscription import admin_tariff_assign_handler

        msg = MagicMock()
        msg.edit_text = AsyncMock()
        callback = self._make_callback(
            data="admin_tariff:assign:pro:30:200",
            msg=msg,
            bot=None,
        )

        mock_admin_user = MagicMock()
        mock_admin_user.id = 10
        mock_admin_user.telegram_id = 100

        mock_target_user = MagicMock()
        mock_target_user.id = 20
        mock_target_user.telegram_id = 200
        mock_target_user.first_name = "Target"
        mock_target_user.timezone = "Europe/Moscow"

        mock_tier = MagicMock()
        mock_tier.code = "pro"
        mock_tier.name = "PRO"

        class FakeUserRepo:
            def __init__(self, session):
                self._map = {100: mock_admin_user, 200: mock_target_user}

            async def get_by_telegram_id(self, telegram_id: int):
                return self._map.get(telegram_id)

        class FakeSubService:
            def __init__(self, session):
                self.session = session

            async def get_tier_by_code(self, code: str):
                return mock_tier

            async def assign_admin_subscription(self, **kwargs):
                raise ValueError("DB error")

        class FakeSessionFactory:
            def __init__(self):
                self.session = MagicMock()
                self.session.commit = AsyncMock()

            async def __aenter__(self):
                return self.session

            async def __aexit__(self, *args):
                pass

        with patch(
            "app.bot.handlers.subscription.UserRepository",
            FakeUserRepo,
        ), patch(
            "app.bot.handlers.subscription.SubscriptionService",
            FakeSubService,
        ), patch(
            "app.bot.handlers.subscription.AsyncSessionFactory",
            FakeSessionFactory,
        ), patch(
            "app.bot.handlers.subscription.get_settings",
            return_value=self._mock_settings(),
        ), patch(
            "app.bot.handlers.subscription._callback_message",
            return_value=msg,
        ):
            await admin_tariff_assign_handler(callback)

        callback.answer.assert_called()
        # Check that at least one call had show_alert=True
        show_alert_used = any(
            call_kwargs.get("show_alert") is True
            for call_args, call_kwargs in callback.answer.call_args_list
        )
        assert show_alert_used
        msg.edit_text.assert_not_called()
