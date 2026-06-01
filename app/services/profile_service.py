"""version: 1.0.0
description: User profile management service.
"""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import User

logger = logging.getLogger(__name__)

PHONE_PATTERN = re.compile(r"^\+?[\d\s\-()]{10,20}$")
EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


class ProfileValidationError(Exception):
    pass


@dataclass
class ProfileUpdateData:
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    email: str | None = None
    company_name: str | None = None
    inn: str | None = None
    ogrn: str | None = None
    timezone: str | None = None


@dataclass
class ProfileData:
    user_id: int
    telegram_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    display_name: str
    phone: str | None
    email: str | None
    company_name: str | None
    inn: str | None
    ogrn: str | None
    timezone: str
    tariff: str
    notifications_enabled: bool
    created_at: datetime
    last_activity_at: datetime | None
    last_login_at: datetime | None
    last_login_ip: str | None


class ProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_profile(self, user_id: int) -> ProfileData:
        user = await self.session.get(User, user_id)
        if user is None:
            raise ProfileValidationError("Пользователь не найден")

        display_name = (
            user.first_name
            or user.last_name
            or user.username
            or str(user.telegram_id)
        )

        return ProfileData(
            user_id=user.id,
            telegram_id=user.telegram_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            display_name=display_name,
            phone=user.phone,
            email=user.email,
            company_name=user.company_name,
            inn=user.inn,
            ogrn=user.ogrn,
            timezone=user.timezone,
            tariff=user.tariff,
            notifications_enabled=user.notifications_enabled,
            created_at=user.created_at,
            last_activity_at=user.last_activity_at,
            last_login_at=user.last_login_at,
            last_login_ip=user.last_login_ip,
        )

    async def update_profile(self, user_id: int, data: ProfileUpdateData) -> User:
        user = await self.session.get(User, user_id)
        if user is None:
            raise ProfileValidationError("Пользователь не найден")

        if data.phone is not None:
            self._validate_phone(data.phone)
            user.phone = data.phone.strip() if data.phone.strip() else None

        if data.email is not None:
            self._validate_email(data.email)
            user.email = data.email.strip().lower() if data.email.strip() else None

        if data.first_name is not None:
            user.first_name = data.first_name.strip()[:255] if data.first_name.strip() else None

        if data.last_name is not None:
            user.last_name = data.last_name.strip()[:255] if data.last_name.strip() else None

        if data.company_name is not None:
            cleaned = data.company_name.strip()
            user.company_name = cleaned[:255] if cleaned else None

        if data.inn is not None:
            self._validate_inn(data.inn)
            user.inn = data.inn.strip() if data.inn.strip() else None

        if data.ogrn is not None:
            self._validate_ogrn(data.ogrn)
            user.ogrn = data.ogrn.strip() if data.ogrn.strip() else None

        if data.timezone is not None:
            user.timezone = data.timezone[:64]

        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def update_last_activity(self, user_id: int) -> None:
        user = await self.session.get(User, user_id)
        if user is not None:
            user.last_activity_at = datetime.now(UTC)
            await self.session.commit()

    async def record_login(
        self, user_id: int, ip_address: str | None, user_agent: str | None
    ) -> None:
        user = await self.session.get(User, user_id)
        if user is not None:
            now = datetime.now(UTC)
            user.last_login_at = now
            user.last_activity_at = now
            user.last_login_ip = ip_address[:64] if ip_address else None
            user.last_login_user_agent = user_agent[:512] if user_agent else None
            await self.session.commit()

    @staticmethod
    def _validate_phone(phone: str) -> None:
        cleaned = phone.strip()
        if cleaned and not PHONE_PATTERN.match(cleaned):
            raise ProfileValidationError("Некорректный формат телефона")

    @staticmethod
    def _validate_email(email: str) -> None:
        cleaned = email.strip()
        if cleaned and not EMAIL_PATTERN.match(cleaned):
            raise ProfileValidationError("Некорректный формат email")

    @staticmethod
    def _validate_inn(inn: str) -> None:
        cleaned = inn.strip()
        if cleaned and (not cleaned.isdigit() or len(cleaned) not in (10, 12)):
            raise ProfileValidationError("ИНН должен содержать 10 или 12 цифр")

    @staticmethod
    def _validate_ogrn(ogrn: str) -> None:
        cleaned = ogrn.strip()
        if cleaned and (not cleaned.isdigit() or len(cleaned) not in (13, 15)):
            raise ProfileValidationError("ОГРН/ОГРНИП должен содержать 13 или 15 цифр")
