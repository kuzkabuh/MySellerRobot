"""version: 1.0.0
description: Unit tests for polished Telegram message formatters.
updated: 2026-05-17
"""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.bot.formatters.common import (
    compact_external_id,
    format_empty_state,
    format_fbs_deadline_alert,
    format_percent,
    format_recent_orders,
    format_stock_rows,
)
from app.models.enums import Marketplace, SaleModel


def test_recent_orders_formatter_uses_card_layout_not_technical_log() -> None:
    orders = [
        SimpleNamespace(
            marketplace=Marketplace.OZON,
            sale_model=SaleModel.FBS,
            order_date=datetime(2026, 5, 16, 18, 19, tzinfo=UTC),
            order_external_id="16039101-0748-4",
            requires_seller_action=True,
        ),
        SimpleNamespace(
            marketplace=Marketplace.WB,
            sale_model=SaleModel.FBO,
            order_date=datetime(2026, 5, 16, 17, 44, tzinfo=UTC),
            order_external_id="ec.r3a1b55dc44e34b14b23dd6940a956eea.0.0",
            requires_seller_action=False,
        ),
    ]

    text = format_recent_orders(orders, timezone_name="Europe/Moscow")

    assert "🛒 <b>Последние заказы</b>" in text
    assert "⚠️ <b>🔵 Ozon · FBS</b>" in text
    assert "ℹ️ <b>🟣 WB · FBO</b>" in text
    assert "• Дата: 16.05.2026, 21:19" in text
    assert "• Заказ: <code>16039101-0748-4</code>" in text
    assert "ec.r3a1b55" not in text or "…" in text
    assert "— 16.05.2026" not in text
    assert "#16039101-0748-4:" not in text


def test_recent_orders_formatter_escapes_external_values() -> None:
    orders = [
        SimpleNamespace(
            marketplace=Marketplace.OZON,
            sale_model=SaleModel.FBS,
            order_date=datetime(2026, 5, 16, 18, 19, tzinfo=UTC),
            order_external_id="Крем <новый> & тест",
            requires_seller_action=True,
        )
    ]

    text = format_recent_orders(orders)

    assert "<новый>" not in text
    assert "Крем &lt;новый&gt; &amp; тест" in text


def test_empty_state_has_consistent_structure() -> None:
    text = format_empty_state(
        icon="📦",
        title="Остатки пока не загружены",
        body="Данные появятся после успешной синхронизации кабинета маркетплейса.",
    )

    assert text.startswith("📦 <b>Остатки пока не загружены</b>")
    assert "Данные появятся" in text


def test_stock_formatter_uses_readable_blocks() -> None:
    rows = [
        SimpleNamespace(
            seller_article="SKU<1>",
            quantity=4,
            warehouse="Основной & тест",
            days_until_stockout=3,
            lost_revenue_30d=Decimal("24530"),
        )
    ]

    text = format_stock_rows(rows)

    assert "📦 <b>Остатки и прогноз</b>" in text
    assert "SKU&lt;1&gt;" in text
    assert "Остаток: 4 шт." in text
    assert "24 530 ₽" in text


def test_fbs_deadline_formatter_is_not_raw_log() -> None:
    orders = [
        SimpleNamespace(
            marketplace=Marketplace.WB,
            sale_model=SaleModel.FBS,
            order_external_id="5055378321",
            processing_deadline_at=datetime(2026, 5, 16, 20, 0, tzinfo=UTC),
            deadline_at=None,
        )
    ]

    text = format_fbs_deadline_alert(orders)

    assert "⚠️ <b>Риск просрочки FBS / rFBS</b>" in text
    assert "<b>Wildberries · FBS</b>" in text
    assert "• Заказ: <code>5055378321</code>" in text
    assert "WB: FBS заказ" not in text


def test_compact_external_id_and_percent_format() -> None:
    assert compact_external_id("ec.r3a1b55dc44e34b14b23dd6940a956eea.0.0") == (
        "ec.r3a1b55…a956eea.0.0"
    )
    assert format_percent(Decimal("18.44")) == "18,4%"
