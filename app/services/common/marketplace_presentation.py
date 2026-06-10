"""Shared seller-facing labels for marketplaces, order states, and sources."""

from app.models.enums import Marketplace, SaleModel, SourceEventType


def marketplace_title(value: Marketplace | str | None) -> str:
    raw = _raw(value)
    if raw == Marketplace.WB.value:
        return "Wildberries"
    if raw == Marketplace.OZON.value:
        return "Ozon"
    return str(raw or "Маркетплейс")


def marketplace_marker(value: Marketplace | str | None) -> str:
    raw = _raw(value)
    if raw == Marketplace.WB.value:
        return "🟣 WB"
    if raw == Marketplace.OZON.value:
        return "🔵 Ozon"
    return "⚪ МП"


def marketplace_css_class(value: Marketplace | str | None) -> str:
    raw = _raw(value)
    if raw == Marketplace.WB.value:
        return "wb"
    if raw == Marketplace.OZON.value:
        return "ozon"
    return "neutral"


def sale_model_title(value: SaleModel | str | None) -> str:
    raw = _raw(value)
    if raw == "FBO":
        return "FBO"
    if raw == "FBS":
        return "FBS"
    if raw == "rFBS":
        return "rFBS"
    if raw == "DBS":
        return "DBS"
    if raw == "DBW":
        return "DBW"
    return str(raw or "н/д")


def order_status_label(status: str | None, requires_action: bool = False) -> str:
    normalized = (status or "").strip().lower()
    mapping = {
        "new": "Новый заказ",
        "ordered": "Заказ оформлен",
        "awaiting_packaging": "Ожидает упаковки",
        "awaiting_deliver": "Ожидает отгрузки",
        "awaiting_delivery": "Ожидает доставки",
        "delivering": "В доставке",
        "delivered": "Доставлен",
        "completed": "Завершён",
        "complete": "Завершён",
        "cancelled": "Отменён",
        "canceled": "Отменён",
        "cancel": "Отменён",
        "return": "Возврат",
        "returned": "Возврат",
    }
    if normalized in mapping:
        return mapping[normalized]
    if requires_action:
        return "Требует обработки"
    return status or "н/д"


def order_status_tone(status: str | None, requires_action: bool = False) -> str:
    normalized = (status or "").strip().lower()
    if normalized in {"cancelled", "canceled", "cancel", "return", "returned"}:
        return "bad"
    if requires_action or normalized in {"new", "awaiting_packaging", "awaiting_deliver"}:
        return "warn"
    if normalized in {"delivered", "completed", "complete"}:
        return "good"
    return "neutral"


def source_event_label(value: SourceEventType | str | None) -> str:
    raw = _raw(value)
    mapping = {
        "POSTING_EVENT": "API Ozon: отправление",
        "STATISTICS_ORDER": "API WB: заказ",
        "LIVE_ORDER": "API WB: заказ",
        "REPORT_ORDER": "Файл отчёта WB",
        "FBS_ORDER": "API WB: заказ",
        "FBO_ORDER": "API Ozon: заказ",
    }
    return mapping.get(str(raw or ""), str(raw or "н/д"))


def _raw(value: object | None) -> object | None:
    return value.value if hasattr(value, "value") else value
