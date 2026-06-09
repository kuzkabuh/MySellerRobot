"""version: 1.1.0
description: Compatibility facade. Moved to app.services.common.marketplace_presentation.
updated: 2026-06-09
"""

from app.services.common.marketplace_presentation import (  # noqa: F401
    marketplace_css_class,
    marketplace_marker,
    marketplace_title,
    order_status_label,
    order_status_tone,
    sale_model_title,
    source_event_label,
)

__all__ = ['marketplace_css_class', 'marketplace_marker', 'marketplace_title', 'order_status_label', 'order_status_tone', 'sale_model_title', 'source_event_label']
