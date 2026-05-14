"""version: 1.0.0
description: Unit tests for order notification policy and FBO digest formatting.
updated: 2026-05-14
"""

from datetime import UTC, datetime
from decimal import Decimal

from app.models.domain import FboDigestQueue
from app.models.enums import FboNotificationMode, Marketplace, SaleModel
from app.services.fbo_digest_service import FboDigestService
from app.services.order_notification_policy import OrderNotificationPolicyService


def test_default_policy_sends_fbs_and_queues_fbo_digest() -> None:
    policy = OrderNotificationPolicyService.from_sources({})

    assert policy.is_instant_enabled_for(SaleModel.FBS) is True
    assert policy.is_instant_enabled_for(SaleModel.RFBS) is True
    assert policy.is_instant_enabled_for(SaleModel.FBO) is False
    assert policy.should_queue_fbo_digest(SaleModel.FBO) is True


def test_policy_can_send_fbo_instantly() -> None:
    policy = OrderNotificationPolicyService.from_sources(
        {"fbo_notification_mode": FboNotificationMode.INSTANT.value}
    )

    assert policy.is_instant_enabled_for(SaleModel.FBO) is True
    assert policy.should_queue_fbo_digest(SaleModel.FBO) is False


def test_policy_can_disable_fbo_until_daily_report() -> None:
    policy = OrderNotificationPolicyService.from_sources(
        {"fbo_notification_mode": FboNotificationMode.DAILY_ONLY.value}
    )

    assert policy.is_instant_enabled_for(SaleModel.FBO) is False
    assert policy.should_queue_fbo_digest(SaleModel.FBO) is False


def test_fbo_digest_formats_marketplace_totals() -> None:
    rows = [
        FboDigestQueue(
            id=1,
            user_id=1,
            order_id=10,
            marketplace=Marketplace.WB,
            revenue=Decimal("1200"),
            estimated_profit=Decimal("250"),
            queued_at=datetime(2026, 5, 14, 9, 0, tzinfo=UTC),
            mode=FboNotificationMode.DIGEST_30_MIN,
        ),
        FboDigestQueue(
            id=2,
            user_id=1,
            order_id=11,
            marketplace=Marketplace.OZON,
            revenue=Decimal("800"),
            estimated_profit=Decimal("150"),
            queued_at=datetime(2026, 5, 14, 9, 10, tzinfo=UTC),
            mode=FboNotificationMode.DIGEST_30_MIN,
        ),
    ]

    text = FboDigestService.format_digest(rows)

    assert "Новые FBO-заказы за последние 30 минут" in text
    assert "Wildberries:" in text
    assert "Ozon:" in text
    assert "2 заказов" in text
    assert "2 000 ₽" in text
    assert "400 ₽" in text
