"""Tests for subscription text formatter service."""

from decimal import Decimal

from app.models.subscriptions import SubscriptionTier
from app.services.subscriptions.subscription_text_formatter import (
    TIER_FEATURE_NAMES,
    build_tier_card,
    format_current_subscription,
    format_pricing_overview,
    format_subscription_help,
    format_tier_card,
)


def _make_tier(
    code: str = "pro",
    name: str = "PRO",
    price_monthly: Decimal | None = Decimal("1490"),
    price_yearly: Decimal | None = Decimal("14900"),
    max_mp: int = 5,
    max_orders: int | None = None,
    max_products: int | None = None,
    web_cabinet: bool = True,
    analytics: bool = True,
    plan_fact: bool = True,
    break_even: bool = True,
    stock_forecast: bool = True,
    alerts: bool = True,
    priority_support: bool = True,
    api_access: bool = False,
) -> SubscriptionTier:
    """Helper to create a SubscriptionTier for testing."""
    return SubscriptionTier(
        code=code,
        name=name,
        description=f"Description for {name}",
        price_monthly=price_monthly or Decimal("0"),
        price_yearly=price_yearly,
        max_marketplace_accounts=max_mp,
        max_orders_per_month=max_orders,
        max_products=max_products,
        feature_web_cabinet=web_cabinet,
        feature_analytics=analytics,
        feature_plan_fact=plan_fact,
        feature_break_even=break_even,
        feature_stock_forecast=stock_forecast,
        feature_alerts=alerts,
        feature_priority_support=priority_support,
        feature_api_access=api_access,
        is_active=True,
        sort_order=0,
    )


class TestBuildTierCard:
    def test_build_pro_card(self) -> None:
        tier = _make_tier()
        card = build_tier_card(tier)

        assert card.code == "pro"
        assert card.name == "PRO"
        assert card.emoji == "💎"
        assert card.price_monthly == Decimal("1490")
        assert card.price_yearly == Decimal("14900")
        assert card.max_marketplace_accounts == 5
        assert card.max_orders_per_month == "без ограничений"
        assert card.max_products == "без ограничений"
        assert len(card.features) == len(TIER_FEATURE_NAMES)

    def test_build_free_card(self) -> None:
        tier = _make_tier(
            code="free",
            name="FREE",
            price_monthly=Decimal("0"),
            price_yearly=Decimal("0"),
            max_mp=1,
            max_orders=100,
            max_products=100,
            web_cabinet=True,
            analytics=False,
            plan_fact=False,
            break_even=False,
            stock_forecast=False,
            alerts=False,
            priority_support=False,
            api_access=False,
        )
        card = build_tier_card(tier)

        assert card.code == "free"
        assert card.emoji == "🆓"
        assert card.price_monthly is None
        assert card.price_yearly is None
        assert card.max_marketplace_accounts == 1
        assert card.max_orders_per_month == 100

    def test_build_enterprise_card(self) -> None:
        tier = _make_tier(
            code="enterprise",
            name="ENTERPRISE",
            price_monthly=Decimal("0"),
            price_yearly=Decimal("0"),
            max_mp=999,
            max_orders=None,
            max_products=None,
            web_cabinet=True,
            analytics=True,
            plan_fact=True,
            break_even=True,
            stock_forecast=True,
            alerts=True,
            priority_support=True,
            api_access=True,
        )
        card = build_tier_card(tier)

        assert card.code == "enterprise"
        assert card.emoji == "🏢"
        assert card.price_monthly is None
        assert card.price_yearly is None
        assert card.max_marketplace_accounts == "индивидуально"
        assert card.max_orders_per_month == "индивидуально"
        assert card.max_products == "индивидуально"
        assert card.additional_info is not None
        assert len(card.additional_info) == 4

    def test_is_current_flag(self) -> None:
        tier = _make_tier()
        card = build_tier_card(tier, is_current=True)
        assert card.is_current is True

        card2 = build_tier_card(tier, is_current=False)
        assert card2.is_current is False


class TestFormatTierCard:
    def test_pro_card_contains_required_sections(self) -> None:
        tier = _make_tier()
        card = build_tier_card(tier)
        text = format_tier_card(card)

        assert "PRO" in text
        assert "1 490 ₽" in text
        assert "14 900 ₽" in text
        assert "Кабинетов МП: 5" in text
        assert "Заказов в месяц: без ограничений" in text
        assert "SKU в аналитике: без ограничений" in text
        assert "✅ Web-кабинет" in text
        assert "✅ Расширенная аналитика" in text
        assert "✅ План/факт анализ" in text
        assert "❌ API-доступ" in text

    def test_free_card_format(self) -> None:
        tier = _make_tier(
            code="free",
            name="FREE",
            price_monthly=Decimal("0"),
            price_yearly=Decimal("0"),
            max_mp=1,
            max_orders=100,
            max_products=100,
            web_cabinet=True,
            analytics=False,
            plan_fact=False,
            break_even=False,
            stock_forecast=False,
            alerts=False,
            priority_support=False,
            api_access=False,
        )
        card = build_tier_card(tier)
        text = format_tier_card(card)

        assert "FREE" in text
        assert "Бесплатно" in text
        assert "Кабинетов МП: 1" in text
        assert "Заказов в месяц: 100" in text
        assert "✅ Web-кабинет" in text
        assert "❌ Расширенная аналитика" in text

    def test_enterprise_card_format(self) -> None:
        tier = _make_tier(
            code="enterprise",
            name="ENTERPRISE",
            price_monthly=Decimal("0"),
            price_yearly=Decimal("0"),
            max_mp=999,
            max_orders=None,
            max_products=None,
            web_cabinet=True,
            analytics=True,
            plan_fact=True,
            break_even=True,
            stock_forecast=True,
            alerts=True,
            priority_support=True,
            api_access=True,
        )
        card = build_tier_card(tier)
        text = format_tier_card(card)

        assert "ENTERPRISE" in text
        assert "Индивидуальные условия" in text
        assert "Кабинетов МП: индивидуально" in text
        assert "Дополнительно:" in text
        assert "Индивидуальные лимиты" in text
        assert "Роли и команды" in text

    def test_current_tier_marker(self) -> None:
        tier = _make_tier()
        card = build_tier_card(tier, is_current=True)
        text = format_tier_card(card)

        assert "Это ваш текущий тариф" in text

    def test_dynamic_tier_values_are_html_escaped(self) -> None:
        tier = _make_tier(name="PRO <script>")
        card = build_tier_card(tier)
        text = format_tier_card(card)

        assert "PRO &lt;script&gt;" in text
        assert "PRO <script>" not in text

    def test_non_current_tier_no_marker(self) -> None:
        tier = _make_tier()
        card = build_tier_card(tier, is_current=False)
        text = format_tier_card(card)

        assert "Это ваш текущий тариф" not in text


class TestFormatPricingOverview:
    def test_overview_contains_all_tiers(self) -> None:
        tiers = [
            build_tier_card(
                _make_tier(
                    code="free",
                    name="FREE",
                    price_monthly=Decimal("0"),
                    price_yearly=Decimal("0"),
                    max_mp=1,
                    max_orders=100,
                    max_products=100,
                    web_cabinet=True,
                    analytics=False,
                    plan_fact=False,
                    break_even=False,
                    stock_forecast=False,
                    alerts=False,
                    priority_support=False,
                    api_access=False,
                )
            ),
            build_tier_card(
                _make_tier(
                    code="basic",
                    name="BASIC",
                    price_monthly=Decimal("490"),
                    price_yearly=Decimal("4900"),
                    max_mp=2,
                    max_orders=1000,
                    max_products=1000,
                    web_cabinet=True,
                    analytics=True,
                    plan_fact=False,
                    break_even=False,
                    stock_forecast=False,
                    alerts=True,
                    priority_support=False,
                    api_access=False,
                )
            ),
            build_tier_card(_make_tier()),
            build_tier_card(
                _make_tier(
                    code="enterprise",
                    name="ENTERPRISE",
                    price_monthly=Decimal("0"),
                    price_yearly=Decimal("0"),
                    max_mp=999,
                    max_orders=None,
                    max_products=None,
                    web_cabinet=True,
                    analytics=True,
                    plan_fact=True,
                    break_even=True,
                    stock_forecast=True,
                    alerts=True,
                    priority_support=True,
                    api_access=True,
                )
            ),
        ]
        text = format_pricing_overview(tiers)

        assert "FREE" in text
        assert "BASIC" in text
        assert "PRO" in text
        assert "ENTERPRISE" in text
        assert "490 ₽" in text
        assert "1 490 ₽" in text
        assert "Выберите тариф ниже" in text


class TestFormatCurrentSubscription:
    def test_free_subscription(self) -> None:
        text = format_current_subscription(
            tier_name="FREE",
            is_free=True,
            features=[("Web-кабинет", True)],
        )

        assert "FREE" in text
        assert "Бесплатный тариф активен" in text
        assert "Web-кабинет" in text
        assert "Чтобы открыть больше возможностей" in text

    def test_active_paid_subscription(self) -> None:
        text = format_current_subscription(
            tier_name="PRO",
            is_active=True,
            expires_at="15.06.2026",
            features=[("План/факт анализ", True)],
            is_free=False,
        )

        assert "PRO" in text
        assert "Активна" in text
        assert "15.06.2026" in text
        assert "План/факт анализ" in text

    def test_trial_subscription(self) -> None:
        text = format_current_subscription(
            tier_name="PRO",
            is_trial=True,
            trial_ends_at="20.06.2026",
            features=[],
            is_free=False,
        )

        assert "Пробный период" in text
        assert "20.06.2026" in text


class TestFormatSubscriptionHelp:
    def test_help_contains_support_link(self) -> None:
        text = format_subscription_help(support_username="mpcontrol_support")

        assert "@mpcontrol_support" in text
        assert "Как работает подписка" in text
        assert "Как оплатить" in text
        assert "Можно ли отменить" in text
        assert "Что будет после окончания" in text
        assert "Есть пробный период" in text

    def test_help_custom_support_username(self) -> None:
        text = format_subscription_help(support_username="custom_support")

        assert "@custom_support" in text
