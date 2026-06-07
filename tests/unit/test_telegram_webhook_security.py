"""version: 1.0.0
description: Тесты fail-closed защиты Telegram webhook.
updated: 2026-06-07
"""

from types import SimpleNamespace

import pytest

from app.api import telegram_webhook as telegram_webhook_module
from app.core.config import Settings


class _Request:
    url = SimpleNamespace(path="/webhook/telegram")

    async def json(self) -> dict:
        raise ValueError("invalid json")


@pytest.mark.asyncio
async def test_telegram_webhook_rejects_missing_secret_by_default(monkeypatch) -> None:
    monkeypatch.setattr(telegram_webhook_module, "get_settings", lambda: Settings())

    with pytest.raises(telegram_webhook_module.HTTPException) as exc_info:
        await telegram_webhook_module.telegram_webhook(_Request())

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_telegram_webhook_rejects_wrong_secret(monkeypatch) -> None:
    monkeypatch.setattr(
        telegram_webhook_module,
        "get_settings",
        lambda: Settings(bot_webhook_secret="expected-secret"),
    )

    with pytest.raises(telegram_webhook_module.HTTPException) as exc_info:
        await telegram_webhook_module.telegram_webhook(
            _Request(),
            x_telegram_bot_api_secret_token="wrong-secret",
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_telegram_webhook_allows_explicit_insecure_dev_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        telegram_webhook_module,
        "get_settings",
        lambda: Settings(app_env="local", webhook_allow_insecure_dev=True),
    )

    response = await telegram_webhook_module.telegram_webhook(_Request())

    assert response.status_code == 400
