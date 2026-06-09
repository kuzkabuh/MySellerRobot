"""version: 1.1.0
description: Compatibility facade. Moved to app.services.subscriptions.subscription_service.
updated: 2026-06-09
"""

from app.services.subscriptions.subscription_service import (  # noqa: F401
    CurrentSubscription,
    SubscriptionService,
    default_free_tier,
    normalize_subscription_period,
    subscription_period_days,
)

__all__ = ['CurrentSubscription', 'SubscriptionService', 'default_free_tier', 'normalize_subscription_period', 'subscription_period_days']
