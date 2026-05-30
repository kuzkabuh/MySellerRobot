"""Tests for web sync route UX: POST works, GET redirects gracefully."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.db import get_session
from app.services.web_auth_service import WEB_SESSION_COOKIE, WebAuthService
from app.services.web_sync_service import WebSyncRequestResult, WebSyncService


class FakeAsyncSession:
    async def execute(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return SimpleNamespace(scalar_one_or_none=lambda: None, scalars=lambda: [])

    async def get(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return None

    def add(self, _value) -> None:  # type: ignore[no-untyped-def]
        return None

    async def flush(self) -> None:
        return None

    async def refresh(self, *_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _web_user() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        telegram_id=12345,
        username="test_user",
        first_name="Test",
        timezone="Europe/Moscow",
        language="ru",
        notifications_enabled=True,
        low_margin_threshold_percent=10,
        tariff="Free",
        status=SimpleNamespace(value="active"),
        subscription_until=None,
    )


def _setup_auth_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_consume(self, token, *, ip_address, user_agent):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            token="web-session-token",
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
        )

    async def fake_get_active_session_user(self, session_hash):  # type: ignore[no-untyped-def]
        return _web_user()

    monkeypatch.setattr(
        WebAuthService,
        "consume_login_token",
        fake_consume,
    )
    monkeypatch.setattr(
        "app.repositories.web_auth.WebAuthRepository.get_active_session_user",
        fake_get_active_session_user,
    )


def _login_and_get_cookie(client: TestClient) -> str:
    response = client.get("/web/login?token=test-token", follow_redirects=False)
    return response.cookies.get(WEB_SESSION_COOKIE, "")


def test_post_sync_ozon_balance_redirects_to_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()

    async def fake_get_session():  # type: ignore[no-untyped-def]
        yield FakeAsyncSession()

    async def fake_request_sync(self, sync_type: str, user_id: int) -> WebSyncRequestResult:  # type: ignore[no-untyped-def]
        return WebSyncRequestResult(queued=True, message="ok")

    app.dependency_overrides[get_session] = fake_get_session
    monkeypatch.setattr(WebSyncService, "request_sync", fake_request_sync)
    _setup_auth_patches(monkeypatch)

    with TestClient(app, raise_server_exceptions=False) as client:
        cookie = _login_and_get_cookie(client)

        response = client.post(
            "/web/sync/ozon-balance",
            cookies={WEB_SESSION_COOKIE: cookie},
            follow_redirects=False,
        )

    app.dependency_overrides.clear()
    assert response.status_code == 303
    assert "/web/accounts?sync=queued" in response.headers.get("location", "")


def test_get_sync_ozon_balance_does_not_return_405(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()

    async def fake_get_session():  # type: ignore[no-untyped-def]
        yield FakeAsyncSession()

    app.dependency_overrides[get_session] = fake_get_session
    _setup_auth_patches(monkeypatch)

    with TestClient(app, raise_server_exceptions=False) as client:
        cookie = _login_and_get_cookie(client)

        response = client.get(
            "/web/sync/ozon-balance",
            cookies={WEB_SESSION_COOKIE: cookie},
            follow_redirects=False,
        )

    app.dependency_overrides.clear()
    assert response.status_code in (302, 303)
    assert "/web/accounts" in response.headers.get("location", "")


def test_get_sync_any_type_redirects_to_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()

    async def fake_get_session():  # type: ignore[no-untyped-def]
        yield FakeAsyncSession()

    app.dependency_overrides[get_session] = fake_get_session
    _setup_auth_patches(monkeypatch)

    with TestClient(app, raise_server_exceptions=False) as client:
        cookie = _login_and_get_cookie(client)

        for sync_type in ("orders", "sales", "stocks", "products", "wb-reports", "ozon-enrichment"):
            response = client.get(
                f"/web/sync/{sync_type}",
                cookies={WEB_SESSION_COOKIE: cookie},
                follow_redirects=False,
            )
            assert response.status_code in (
                302,
                303,
            ), f"GET /web/sync/{sync_type} returned {response.status_code}"
            assert "/web/accounts" in response.headers.get("location", "")

    app.dependency_overrides.clear()
