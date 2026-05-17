"""version: 1.0.0
description: Regression tests for global Telegram navigation commands and FSM reset.
updated: 2026-05-17
"""

from types import SimpleNamespace
from typing import Any

import pytest

from app.bot.handlers.navigation import start_or_menu_handler


class FakeState:
    def __init__(self) -> None:
        self.cleared = False
        self.data = {"draft": "value"}

    async def clear(self) -> None:
        self.cleared = True
        self.data.clear()


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=123, username="seller", first_name="Иван")
        self.answers: list[dict[str, Any]] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append({"text": text, **kwargs})


class FakeSession:
    async def commit(self) -> None:
        return None


class FakeSessionFactory:
    async def __aenter__(self) -> FakeSession:
        return FakeSession()

    async def __aexit__(self, *_: Any) -> None:
        return None


class FakeUserRepository:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def get_or_create(self, **kwargs: Any) -> object:
        return SimpleNamespace(id=1, **kwargs)


@pytest.mark.asyncio
async def test_start_resets_cost_fsm_state_and_opens_main_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.bot.handlers.navigation.AsyncSessionFactory",
        lambda: FakeSessionFactory(),
    )
    monkeypatch.setattr("app.bot.handlers.navigation.UserRepository", FakeUserRepository)
    message = FakeMessage("/start")
    state = FakeState()

    await start_or_menu_handler(message, state)  # type: ignore[arg-type]

    assert state.cleared is True
    assert state.data == {}
    assert message.answers
    assert "Привет! Я помогу" in message.answers[0]["text"]
    assert "Нужен формат" not in message.answers[0]["text"]
    assert message.answers[0]["reply_markup"] is not None


@pytest.mark.asyncio
async def test_menu_resets_any_active_fsm_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.bot.handlers.navigation.AsyncSessionFactory",
        lambda: FakeSessionFactory(),
    )
    monkeypatch.setattr("app.bot.handlers.navigation.UserRepository", FakeUserRepository)
    message = FakeMessage("/menu")
    state = FakeState()

    await start_or_menu_handler(message, state)  # type: ignore[arg-type]

    assert state.cleared is True
    assert message.answers
    assert "Привет! Я помогу" in message.answers[0]["text"]
