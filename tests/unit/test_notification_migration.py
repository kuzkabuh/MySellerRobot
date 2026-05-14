"""version: 1.0.0
description: Regression test for order notification enum migration values.
updated: 2026-05-14
"""

from pathlib import Path


def test_notification_type_migration_adds_order_values() -> None:
    migration = Path("migrations/versions/20260514_0005_notification_type_order_modes.py")
    text = migration.read_text(encoding="utf-8")

    assert "ORDER_FBS" in text
    assert "ORDER_RFBS" in text
    assert "ORDER_FBO" in text
    assert "FBO_DIGEST" in text
