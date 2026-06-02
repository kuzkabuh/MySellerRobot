"""Shared dependencies for web cabinet routes."""

import contextvars
import logging

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.models.domain import User
from app.repositories.web_auth import WebAuthRepository
from app.services.web_auth_service import WEB_SESSION_COOKIE, WebAuthService

SESSION_DEPENDENCY = Depends(get_session)
WEB_DASHBOARD_PATH = "/web/"
WEB_LOGIN_REQUIRED_PATH = "/web/login-required"
WEB_SESSION_COOKIE_PATH = "/"
CURRENT_WEB_USER: contextvars.ContextVar[User | None] = contextvars.ContextVar(
    "current_web_user",
    default=None,
)
logger = logging.getLogger(__name__)


def is_admin_user(user: User | None) -> bool:
    if user is None:
        return False
    role = str(getattr(user, "role", "") or "").lower()
    if role in {"admin", "superadmin"}:
        return True
    telegram_id = getattr(user, "telegram_id", None)
    return isinstance(telegram_id, int) and telegram_id in get_settings().admin_ids


def current_user_role(user: User | None) -> str:
    role = str(getattr(user, "role", "") or "").lower()
    if role:
        return role
    return "admin" if is_admin_user(user) else "user"


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
    if user is None:
        raise HTTPException(status_code=401, detail="Сессия истекла")
    CURRENT_WEB_USER.set(user)
    logger.info(
        "WEB AUTH",
        extra={
            "user_id": user.id,
            "telegram_id": user.telegram_id,
            "role": current_user_role(user),
            "is_admin": is_admin_user(user),
        },
    )
    return user


CURRENT_WEB_USER_DEPENDENCY = Depends(current_web_user)


async def require_admin_user(user: User = CURRENT_WEB_USER_DEPENDENCY) -> User:
    if not is_admin_user(user):
        logger.warning(
            "web_admin_unauthorized_access",
            extra={
                "user_id": getattr(user, "id", None),
                "telegram_id": getattr(user, "telegram_id", None),
                "role": current_user_role(user),
            },
        )
        raise HTTPException(status_code=403, detail="У вас нет доступа к этому разделу")
    return user


ADMIN_WEB_USER_DEPENDENCY = Depends(require_admin_user)
