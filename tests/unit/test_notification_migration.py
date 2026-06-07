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


def test_sales_event_migration_adds_buyout_values() -> None:
    migration = Path("migrations/versions/20260514_0006_sales_events_buyouts.py")
    text = migration.read_text(encoding="utf-8")

    assert "SALE_COMPLETED" in text
    assert "SALE_DIGEST" in text
    assert "notification_sent_at" in text
    assert "saleeventtype" in text


def test_notification_settings_migration_adds_partial_unique_indexes() -> None:
    migration = Path(
        "migrations/versions/20260607_0057_notification_settings_unique_indexes.py"
    )
    text = migration.read_text(encoding="utf-8")

    assert "uq_notification_settings_global" in text
    assert "WHERE marketplace_account_id IS NULL" in text
    assert "uq_notification_settings_account" in text
    assert "WHERE marketplace_account_id IS NOT NULL" in text
