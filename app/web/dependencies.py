"""Shared dependencies for web cabinet routes."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models.domain import User
from app.repositories.web_auth import WebAuthRepository
from app.services.web_auth_service import WEB_SESSION_COOKIE, WebAuthService

SESSION_DEPENDENCY = Depends(get_session)
WEB_DASHBOARD_PATH = "/web/"
WEB_LOGIN_REQUIRED_PATH = "/web/login-required"
WEB_SESSION_COOKIE_PATH = "/"


async def current_web_user(
    request: Request,
    session: AsyncSession = SESSION_DEPENDENCY,
) -> User:
    raw_session = request.cookies.get(WEB_SESSION_COOKIE)
    if not raw_session:
        raise HTTPException(status_code=401, detail="Требуется вход в web-кабинет")
    user = await WebAuthRepository(session).get_active_session_user(
        WebAuthService.hash_secret(raw_session)
    )
    await session.commit()
    if user is None:
        raise HTTPException(status_code=401, detail="Сессия истекла")
    return user


CURRENT_WEB_USER_DEPENDENCY = Depends(current_web_user)
