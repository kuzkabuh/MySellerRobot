"""version: 1.0.0
description: Daily summary report service.
updated: 2026-05-14
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.orders import OrderRepository


class DailyReportService:
    """Build compact Russian daily reports."""

    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session

    async def build_payload(
        self,
        user_id: int,
        report_date: date,
    ) -> dict[str, dict[str, Decimal | int]]:
        if self.session is None:
            raise RuntimeError("Для построения отчёта нужна DB-сессия")
        return await OrderRepository(self.session).daily_marketplace_summary(user_id, report_date)

    def format_report(self, report_date: date, payload: dict[str, dict[str, Decimal | int]]) -> str:
        lines = [f"📊 Итоги за {report_date:%d.%m.%Y}", ""]
        total_revenue = Decimal("0")
        total_profit = Decimal("0")
        for marketplace, data in payload.items():
            revenue = Decimal(str(data.get("revenue", 0)))
            profit = Decimal(str(data.get("estimated_profit", 0)))
            total_revenue += revenue
            total_profit += profit
            lines.extend(
                [
                    f"{marketplace}:",
                    f"— Заказов: {data.get('orders', 0)} на {revenue:.0f} ₽",
                    f"— Продаж: {data.get('sales', 0)}",
                    f"— Возвратов: {data.get('returns', 0)}",
                    f"— Отмен: {data.get('cancellations', 0)}",
                    f"— Плановая прибыль: {profit:.0f} ₽",
                    "",
                ]
            )
        lines.extend(
            [
                "Итого:",
                f"💰 Выручка: {total_revenue:.0f} ₽",
                f"📈 Плановая прибыль: {total_profit:.0f} ₽",
            ]
        )
        return "\n".join(lines)

    def format_today_summary(self, payload: dict[str, dict[str, Decimal | int]]) -> str:
        if not payload:
            return "📊 За сегодня пока нет заказов."
        return self.format_report(date.today(), payload).replace("Итоги за", "Сегодня на")
