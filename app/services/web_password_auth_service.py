"""Password login settings and verification for web cabinet."""

import base64
import hashlib
import hmac
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import User
from app.repositories.web_auth import WebAuthRepository
from app.services.web_auth_service import WebAuthService, WebSession

logger = logging.getLogger(__name__)

LOGIN_RE = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")
PASSWORD_MIN_LENGTH = 8
PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 260_000
LOGIN_RATE_LIMIT_ATTEMPTS = 5
LOGIN_RATE_LIMIT_WINDOW = timedelta(minutes=15)
_FAILED_LOGIN_ATTEMPTS: dict[str, list[datetime]] = {}


class WebPasswordAuthError(ValueError):
    pass


@dataclass(slots=True)
class PasswordSettingsResult:
    message: str
    user: User


class WebPasswordAuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = WebAuthRepository(session)

    async def update_password_login(
        self,
        user: User,
        *,
        login: str,
        password: str,
        password_confirm: str,
        enabled: bool,
        current_password: str = "",
    ) -> PasswordSettingsResult:
        normalized_login = self.normalize_login(login)
        if enabled:
            if not normalized_login:
                raise WebPasswordAuthError("Укажите логин для входа")
            if not LOGIN_RE.fullmatch(normalized_login):
                raise WebPasswordAuthError(
                    "Логин должен быть от 3 до 50 символов: "
                    "латиница, цифры, точка, дефис или underscore"
                )
            existing = await self.repo.get_user_by_web_login(normalized_login)
            if existing is not None and existing.id != user.id:
                raise WebPasswordAuthError("Этот логин уже используется")
            if password or password_confirm or not user.web_password_hash:
                if user.web_password_hash and not self.verify_password(
                    current_password, user.web_password_hash
                ):
                    raise WebPasswordAuthError("Укажите текущий пароль")
                if len(password) < PASSWORD_MIN_LENGTH:
                    raise WebPasswordAuthError("Пароль должен быть не короче 8 символов")
                if password != password_confirm:
                    raise WebPasswordAuthError("Пароли не совпадают")
                user.web_password_hash = self.hash_password(password)
                user.web_password_updated_at = datetime.now(UTC)
            user.web_login = normalized_login
            user.web_password_enabled = True
        else:
            user.web_password_enabled = False
            user.web_password_hash = None
            user.web_password_updated_at = datetime.now(UTC)
        await self.session.flush()
        logger.info("web_password_settings_updated", extra={"user_id": user.id})
        return PasswordSettingsResult(message="Настройки входа обновлены", user=user)

    async def disable_password_login(self, user: User) -> None:
        user.web_password_enabled = False
        user.web_password_hash = None
        user.web_password_updated_at = datetime.now(UTC)
        await self.session.flush()
        logger.info("web_password_login_disabled", extra={"user_id": user.id})

    async def authenticate(
        self,
        *,
        login: str,
        password: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> WebSession | None:
        normalized_login = self.normalize_login(login)
        rate_limit_key = self._rate_limit_key(normalized_login, ip_address)
        if self._is_rate_limited(rate_limit_key):
            logger.warning(
                "web_password_login_rate_limited",
                extra={"login": normalized_login[:64], "ip_address": ip_address},
            )
            return None
        user = await self.repo.get_user_by_password_identity(normalized_login)
        if (
            user is None
            or not user.web_password_enabled
            or not user.web_password_hash
            or not self.verify_password(password, user.web_password_hash)
        ):
            self._record_failed_attempt(rate_limit_key)
            logger.info("web_password_login_failed", extra={"login": normalized_login[:64]})
            return None
        self._clear_failed_attempts(rate_limit_key)
        raw_session = secrets.token_urlsafe(48)
        from app.core.config import get_settings

        expires_at = datetime.now(tz=UTC) + timedelta(hours=get_settings().web_session_ttl_hours)
        await self.repo.create_web_session(
            user_id=user.id,
            session_hash=WebAuthService.hash_secret(raw_session),
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        user.last_password_login_at = datetime.now(UTC)
        user.last_login_at = user.last_password_login_at
        user.last_login_ip = ip_address
        user.last_login_user_agent = user_agent[:512] if user_agent else None
        await self.session.flush()
        logger.info(
            "web_password_login_success",
            extra={"user_id": user.id, "telegram_id": user.telegram_id},
        )
        return WebSession(token=raw_session, expires_at=expires_at)

    @staticmethod
    def normalize_login(login: str) -> str:
        return (login or "").strip().lower()

    @staticmethod
    def _rate_limit_key(login: str, ip_address: str | None) -> str:
        return f"{ip_address or 'unknown'}:{login}"

    @staticmethod
    def _recent_attempts(key: str, now: datetime) -> list[datetime]:
        attempts = [
            attempt
            for attempt in _FAILED_LOGIN_ATTEMPTS.get(key, [])
            if now - attempt < LOGIN_RATE_LIMIT_WINDOW
        ]
        if attempts:
            _FAILED_LOGIN_ATTEMPTS[key] = attempts
        else:
            _FAILED_LOGIN_ATTEMPTS.pop(key, None)
        return attempts

    @classmethod
    def _is_rate_limited(cls, key: str) -> bool:
        return len(cls._recent_attempts(key, datetime.now(UTC))) >= LOGIN_RATE_LIMIT_ATTEMPTS

    @classmethod
    def _record_failed_attempt(cls, key: str) -> None:
        now = datetime.now(UTC)
        attempts = cls._recent_attempts(key, now)
        attempts.append(now)
        _FAILED_LOGIN_ATTEMPTS[key] = attempts

    @staticmethod
    def _clear_failed_attempts(key: str) -> None:
        _FAILED_LOGIN_ATTEMPTS.pop(key, None)

    @staticmethod
    def hash_password(password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            PBKDF2_ITERATIONS,
        )
        return (
            f"{PBKDF2_ALGORITHM}${PBKDF2_ITERATIONS}$"
            f"{base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"
        )

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        try:
            algorithm, iterations_text, salt_text, digest_text = password_hash.split("$", 3)
            if algorithm != PBKDF2_ALGORITHM:
                return False
            iterations = int(iterations_text)
            salt = base64.b64decode(salt_text.encode())
            expected = base64.b64decode(digest_text.encode())
        except Exception:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
