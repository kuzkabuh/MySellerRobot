"""version: 1.0.0
description: Unit tests for Telegram daily summary formatting across marketplaces.
updated: 2026-05-14
"""

from datetime import date
from decimal import Decimal

from app.models.enums import Marketplace
from app.services.daily_report_service import DailyReportService


def test_summary_formats_wb_and_ozon_blocks_and_total() -> None:
    payload = {
        Marketplace.WB.value: {
            "orders": 3,
            "sales": 1,
            "sales_revenue": Decimal("1290"),
            "sales_estimated_profit": Decimal("210"),
            "returns": 0,
            "cancellations": 0,
            "revenue": Decimal("3870"),
            "estimated_profit": Decimal("640"),
        },
        Marketplace.OZON.value: {
            "orders": 4,
            "sales": 0,
            "sales_revenue": Decimal("0"),
            "sales_estimated_profit": Decimal("0"),
            "returns": 0,
            "cancellations": 0,
            "revenue": Decimal("4404"),
            "estimated_profit": Decimal("2162"),
        },
    }

    text = DailyReportService().format_report(date(2026, 5, 14), payload)

    assert "📊 <b>Сводка за 14.05.2026</b>" in text
    assert "<b>Продажи и заказы:</b>" in text
    assert "<b>Финансы:</b>" in text
    assert "<b>🟣 Wildberries</b>" in text
    assert "<b>🔵 Ozon</b>" in text
    assert "• Выкупов: 1 на 1 290 ₽" in text
    assert "• Завершённых продаж: 0 на 0 ₽" in text
    assert "• Выкуплено / завершено продаж: 1 290 ₽" in text
    assert "• Выручка по заказам: 8 274 ₽" in text
    assert "• Плановая прибыль: 2 802 ₽" in text


def test_summary_keeps_zero_wb_block() -> None:
    payload = {
        Marketplace.WB.value: {
            "orders": 0,
            "sales": 0,
            "sales_revenue": Decimal("0"),
            "sales_estimated_profit": Decimal("0"),
            "returns": 0,
            "cancellations": 0,
            "revenue": Decimal("0"),
            "estimated_profit": Decimal("0"),
        }
    }

    text = DailyReportService().format_report(date(2026, 5, 14), payload)

    assert "<b>🟣 Wildberries</b>" in text
    assert "• Заказов: 0 на 0 ₽" in text
    assert "• Выручка по заказам: 0 ₽" in text
