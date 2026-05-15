"""version: 1.2.0
description: Unit tests for one-time web cabinet login links and sessions.
updated: 2026-05-15
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.web_auth_service import WebAuthService


class FakeWebAuthRepository:
    def __init__(self) -> None:
        self.created_token_hash: str | None = None
        self.created_session_hash: str | None = None
        self.login_token = SimpleNamespace(
            user_id=5,
            used_at=None,
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=5),
        )

    async def create_login_token(
        self,
        *,
        user_id: int,
        token_hash: str,
        expires_at: datetime,
    ) -> object:
        self.created_token_hash = token_hash
        return SimpleNamespace(user_id=user_id, token_hash=token_hash, expires_at=expires_at)

    async def get_active_login_token(self, token_hash: str) -> object | None:
        return self.login_token if token_hash else None

    async def mark_login_token_used(
        self,
        token: object,
        *,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        token.used_at = datetime.now(tz=UTC)
        token.ip_address = ip_address
        token.user_agent = user_agent

    async def create_web_session(
        self,
        *,
        user_id: int,
        session_hash: str,
        expires_at: datetime,
        ip_address: str | None,
        user_agent: str | None,
    ) -> object:
        self.created_session_hash = session_hash
        return SimpleNamespace(user_id=user_id, session_hash=session_hash, expires_at=expires_at)


def _service(repo: FakeWebAuthRepository) -> WebAuthService:
    service = object.__new__(WebAuthService)
    service.session = object()
    service.settings = SimpleNamespace(
        web_base_url="https://app.mpcontrol.online",
        web_login_token_ttl_minutes=10,
        web_session_ttl_hours=24,
    )
    service.repo = repo
    return service


@pytest.mark.asyncio
async def test_create_login_link_stores_hash_not_raw_token() -> None:
    repo = FakeWebAuthRepository()
    service = _service(repo)

    link = await service.create_login_link(user_id=5)

    assert link.url.startswith("https://app.mpcontrol.online/web/login?token=")
    assert "/web/web" not in link.url
    assert repo.created_token_hash is not None
    assert repo.created_token_hash not in link.url


@pytest.mark.asyncio
async def test_create_login_link_strips_web_suffix_from_base_url() -> None:
    repo = FakeWebAuthRepository()
    service = _service(repo)
    service.settings.web_base_url = "https://app.mpcontrol.online/web"

    link = await service.create_login_link(user_id=5)

    assert link.url.startswith("https://app.mpcontrol.online/web/login?token=")
    assert "/web/web" not in link.url


@pytest.mark.asyncio
async def test_consume_login_token_creates_web_session() -> None:
    repo = FakeWebAuthRepository()
    service = _service(repo)

    session = await service.consume_login_token(
        "raw-token",
        ip_address="127.0.0.1",
        user_agent="pytest",
    )

    assert session is not None
    assert repo.created_session_hash is not None
    assert repo.created_session_hash != session.token
    assert repo.login_token.used_at is not None
