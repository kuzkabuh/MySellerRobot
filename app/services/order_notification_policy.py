"""version: 1.1.0
description: Compatibility facade. Moved to app.services.alerts.order_notification_policy.
updated: 2026-06-09
"""

from app.services.alerts.order_notification_policy import (  # noqa: F401
    OrderNotificationPolicy,
    OrderNotificationPolicyService,
)

__all__ = ['OrderNotificationPolicy', 'OrderNotificationPolicyService']
