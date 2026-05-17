"""version: 1.0.0
description: Unit tests for web cabinet rendering helpers and anti-placeholder UI.
updated: 2026-05-17
"""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.models.enums import Marketplace
from app.web import routes
from app.web.rendering import page


def test_navigation_contains_grouped_web_cabinet_sections() -> None:
    html = page("Главная", "Артем", "<main></main>", active_path="/web/accounts")

    assert "Операции" in html
    assert "Финансы" in html
    assert "Кабинеты МП" in html
    assert 'href="/web/subscription"' in html
    assert 'href="/web/profile"' in html
    assert 'href="/web/web/' not in html
    assert "/web/web" not in html


def test_costs_content_escapes_product_names_and_has_edit_action() -> None:
    product = SimpleNamespace(
        id=10,
        title='<script>alert("x")</script>',
        seller_article="SKU<1>",
        marketplace=Marketplace.WB,
    )
    cost = SimpleNamespace(
        cost_price=Decimal("100.00"),
        package_cost=Decimal("10.00"),
        additional_cost=Decimal("5.00"),
        tax_rate=Decimal("0.0600"),
        valid_from=datetime(2026, 5, 17, tzinfo=UTC),
    )
    data = SimpleNamespace(
        rows=[
            SimpleNamespace(
                product=product,
                account_name="Основной <WB>",
                cost=cost,
                stock_quantity=3,
                orders_count=2,
            )
        ],
        configured_count=1,
        missing_count=0,
    )

    html = routes._costs_content(data)

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Основной &lt;WB&gt;" in html
    assert 'href="/web/costs/10"' in html
    assert 'href="/web/web/' not in html
    assert "Раздел подготовлен" not in html


def test_cost_edit_form_uses_canonical_web_action() -> None:
    product = SimpleNamespace(
        id=97,
        title="Товар",
        seller_article="SKU-97",
        marketplace_article="123",
        external_product_id="123",
        marketplace=Marketplace.OZON,
    )
    history = [
        SimpleNamespace(
            valid_from=datetime(2026, 5, 17, tzinfo=UTC),
            valid_to=None,
            cost_price=Decimal("100.00"),
            package_cost=Decimal("10.00"),
            additional_cost=Decimal("5.00"),
            tax_rate=Decimal("0.0600"),
            comment="Тест",
        )
    ]
    detail = SimpleNamespace(product=product, account_name="Основной", history=history)

    html = routes._cost_edit_content(detail)

    assert 'action="/web/costs/97"' in html
    assert 'action="/web/web/costs/97"' not in html
    assert "/web/web/" not in html


def test_subscription_content_shows_limits_features_and_payments_empty_state() -> None:
    tier = SimpleNamespace(
        code="pro",
        name="PRO",
        description="Профессиональный тариф",
        price_monthly=Decimal("1490.00"),
        max_marketplace_accounts=5,
        max_orders_per_month=None,
        max_products=None,
        feature_web_cabinet=True,
        feature_analytics=True,
        feature_plan_fact=True,
        feature_break_even=True,
        feature_stock_forecast=True,
        feature_alerts=True,
        feature_api_access=False,
    )
    data = SimpleNamespace(
        tier=tier,
        active_subscription=None,
        payments=[],
        used_accounts=2,
        used_orders_month=42,
        used_products=120,
    )

    html = routes._subscription_content(data, [tier])

    assert "Подписка и тариф" in html
    assert "2 / 5" in html
    assert "без ограничений" in html
    assert "Платежей пока нет" in html
    assert "Текущий тариф" in html


def test_control_content_is_real_work_screen_not_placeholder() -> None:
    data = SimpleNamespace(
        report=SimpleNamespace(score=75),
        error_accounts=[],
        open_alerts=[],
        preliminary_orders=3,
        missing_cost_products=2,
        low_stock_products=1,
    )

    html = routes._control_content(data)

    assert "Что требует внимания прямо сейчас" in html
    assert "Предварительная экономика" in html
    assert "Раздел подготовлен" not in html
