"""version: 1.1.0
description: Compatibility facade. Moved to app.services.subscriptions.subscription_text_formatter.
updated: 2026-06-09
"""

from app.services.subscriptions.subscription_text_formatter import (  # noqa: F401
    TierCardInfo,
    TierFeatureInfo,
    build_tier_card,
    format_admin_tariff_confirmation,
    format_current_subscription,
    format_pricing_overview,
    format_subscription_help,
    format_tier_card,
    format_user_tariff_notification,
)

__all__ = ['TierCardInfo', 'TierFeatureInfo', 'build_tier_card', 'format_admin_tariff_confirmation', 'format_current_subscription', 'format_pricing_overview', 'format_subscription_help', 'format_tier_card', 'format_user_tariff_notification']
