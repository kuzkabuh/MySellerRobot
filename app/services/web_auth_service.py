"""version: 1.1.0
description: One-time Telegram-to-web login link and session management service.
updated: 2026-05-15
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.repositories.web_auth import WebAuthRepository

WEB_SESSION_COOKIE = "seller_web_session"
WEB_LOGIN_PATH = "/web/login"


@dataclass(slots=True)
class WebLoginLink:
    url: str
    expires_at: datetime


@dataclass(slots=True)
class WebSession:
    token: str
    expires_at: datetime


class WebAuthService:
    """Issue and consume short-lived web cabinet login links."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()
        self.repo = WebAuthRepository(session)

    async def create_login_link(self, user_id: int) -> WebLoginLink:
        raw_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(tz=UTC) + timedelta(
            minutes=self.settings.web_login_token_ttl_minutes
        )
        await self.repo.create_login_token(
            user_id=user_id,
            token_hash=self.hash_secret(raw_token),
            expires_at=expires_at,
        )
        query = urlencode({"token": raw_token})
        base_url = self._canonical_web_base_url(self.settings.web_base_url)
        return WebLoginLink(url=f"{base_url}{WEB_LOGIN_PATH}?{query}", expires_at=expires_at)

    async def consume_login_token(
        self,
        raw_token: str,
        *,
        ip_address: str | None,
        user_agent: str | None,
    ) -> WebSession | None:
        login_token = await self.repo.get_active_login_token(self.hash_secret(raw_token))
        if login_token is None:
            return None
        await self.repo.mark_login_token_used(
            login_token,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        raw_session = secrets.token_urlsafe(48)
        expires_at = datetime.now(tz=UTC) + timedelta(hours=self.settings.web_session_ttl_hours)
        await self.repo.create_web_session(
            user_id=login_token.user_id,
            session_hash=self.hash_secret(raw_session),
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return WebSession(token=raw_session, expires_at=expires_at)

    async def revoke_session(self, raw_session: str | None) -> bool:
        if not raw_session:
            return False
        return await self.repo.revoke_session(self.hash_secret(raw_session))

    @staticmethod
    def hash_secret(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _canonical_web_base_url(raw_url: str) -> str:
        """Return origin URL without duplicated /web path segments."""

        value = raw_url.rstrip("/")
        parsed = urlsplit(value)
        if parsed.path in {"", "/"}:
            return value
        path = parsed.path.rstrip("/")
        if path == "/web":
            return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        return value
