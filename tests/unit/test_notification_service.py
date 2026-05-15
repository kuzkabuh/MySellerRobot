"""version: 1.0.0
description: Unit tests for visual Telegram notification sending.
updated: 2026-05-15
"""

import pytest

from app.services.notification_service import NotificationService


class FakeBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def send_photo(self, chat_id: int, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.calls.append(("photo", {"chat_id": chat_id, **kwargs}))

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.calls.append(("message", {"chat_id": chat_id, "text": text, **kwargs}))


@pytest.mark.asyncio
async def test_new_order_notification_uses_photo_when_image_exists() -> None:
    bot = FakeBot()
    service = NotificationService(bot)  # type: ignore[arg-type]

    await service.send_new_order(
        100,
        "Карточка заказа",
        order_id=1,
        image_url="https://example.test/image.jpg",
        product_url="https://www.wildberries.ru/catalog/1/detail.aspx?targetUrl=XS",
        parse_mode="HTML",
    )

    assert bot.calls[0][0] == "photo"
    assert bot.calls[0][1]["caption"] == "Карточка заказа"
    assert bot.calls[0][1]["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_new_order_notification_falls_back_to_text_without_image() -> None:
    bot = FakeBot()
    service = NotificationService(bot)  # type: ignore[arg-type]

    await service.send_new_order(100, "Карточка заказа", order_id=1)

    assert bot.calls[0][0] == "message"
    assert bot.calls[0][1]["text"] == "Карточка заказа"
