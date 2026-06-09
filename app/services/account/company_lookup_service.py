"""DaData company lookup and user company profile persistence."""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.domain import User, UserCompanyProfile

logger = logging.getLogger(__name__)

INN_ERROR_MESSAGE = "ИНН должен содержать 10 цифр для организации или 12 цифр для ИП"
LOOKUP_UNAVAILABLE_MESSAGE = "Не удалось загрузить данные по ИНН. Попробуйте позже"
LOOKUP_NOT_FOUND_MESSAGE = "По указанному ИНН компания или ИП не найдены"

_ONLY_DIGITS_RE = re.compile(r"\D+")


class CompanyLookupError(ValueError):
    pass


class DadataNotConfiguredError(CompanyLookupError):
    pass


@dataclass(slots=True)
class CompanyProfileDTO:
    inn: str
    kpp: str | None = None
    ogrn: str | None = None
    name_full: str | None = None
    name_short: str | None = None
    company_type: str | None = None
    status: str | None = None
    address: str | None = None
    okved: str | None = None
    okved_name: str | None = None
    director_name: str | None = None
    registration_date: datetime | None = None
    source: str = "dadata"
    raw_data: dict[str, Any] | None = None

    @property
    def status_warning(self) -> str | None:
        if self.status and self.status.upper() != "ACTIVE":
            return f"По данным справочника компания имеет статус: {self.status}"
        return None


@dataclass(slots=True)
class CompanyLookupResult:
    company: CompanyProfileDTO
    warning: str | None = None


def normalize_inn(raw_inn: str) -> str:
    return _ONLY_DIGITS_RE.sub("", raw_inn or "")


def validate_inn(inn: str) -> bool:
    normalized = normalize_inn(inn)
    if len(normalized) == 10:
        check = _inn_checksum(normalized, [2, 4, 10, 3, 5, 9, 4, 6, 8])
        return check == int(normalized[9])
    if len(normalized) == 12:
        check_11 = _inn_checksum(normalized, [7, 2, 4, 10, 3, 5, 9, 4, 6, 8])
        check_12 = _inn_checksum(normalized, [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8])
        return check_11 == int(normalized[10]) and check_12 == int(normalized[11])
    return False


def _inn_checksum(inn: str, factors: list[int]) -> int:
    return sum(int(digit) * factor for digit, factor in zip(inn, factors, strict=False)) % 11 % 10


def map_dadata_party_to_company_profile(data: dict[str, Any]) -> CompanyProfileDTO:
    party = data.get("data") or {}
    name = party.get("name") or {}
    state = party.get("state") or {}
    address = party.get("address") or {}
    management = party.get("management") or {}

    return CompanyProfileDTO(
        inn=str(party.get("inn") or ""),
        kpp=_string_or_none(party.get("kpp")),
        ogrn=_string_or_none(party.get("ogrn") or party.get("ogrnip")),
        name_full=_string_or_none(name.get("full") or data.get("unrestricted_value")),
        name_short=_string_or_none(name.get("short") or data.get("value")),
        company_type=_company_type_label(party.get("type")),
        status=_string_or_none(state.get("status")),
        address=_string_or_none(address.get("unrestricted_value") or address.get("value")),
        okved=_string_or_none(party.get("okved")),
        okved_name=_string_or_none(party.get("okved_name")),
        director_name=_string_or_none(management.get("name")),
        registration_date=_date_from_dadata(state.get("registration_date")),
        source="dadata",
        raw_data=data,
    )


class CompanyLookupService:
    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session

    async def fetch_company_by_inn(self, inn: str) -> CompanyLookupResult:
        normalized = normalize_inn(inn)
        if not validate_inn(normalized):
            raise CompanyLookupError(INN_ERROR_MESSAGE)

        settings = get_settings()
        api_key = settings.dadata_api_key.get_secret_value()
        secret_key = settings.dadata_secret_key.get_secret_value()
        if not api_key:
            logger.error("dadata_api_key_not_configured")
            raise DadataNotConfiguredError(LOOKUP_UNAVAILABLE_MESSAGE)

        headers = {
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
        }
        if secret_key:
            headers["X-Secret"] = secret_key

        url = f"{settings.dadata_base_url.rstrip('/')}/findById/party"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(url, headers=headers, json={"query": normalized})
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.warning(
                "dadata_company_lookup_failed",
                extra={"inn": normalized, "error_type": type(exc).__name__},
            )
            raise CompanyLookupError(LOOKUP_UNAVAILABLE_MESSAGE) from exc

        suggestions = payload.get("suggestions") or []
        exact = [
            item
            for item in suggestions
            if str((item.get("data") or {}).get("inn") or "") == normalized
        ]
        if not exact:
            raise CompanyLookupError(LOOKUP_NOT_FOUND_MESSAGE)

        company = map_dadata_party_to_company_profile(exact[0])
        return CompanyLookupResult(company=company, warning=company.status_warning)

    async def get_user_company_profile(self, user_id: int) -> UserCompanyProfile | None:
        if self.session is None:
            raise RuntimeError("Session is required")
        result = await self.session.execute(
            select(UserCompanyProfile).where(UserCompanyProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def save_company_profile(
        self,
        user: User,
        company: CompanyProfileDTO,
    ) -> UserCompanyProfile:
        if self.session is None:
            raise RuntimeError("Session is required")
        profile = await self.get_user_company_profile(user.id)
        if profile is None:
            profile = UserCompanyProfile(user_id=user.id, inn=company.inn)
            self.session.add(profile)
        _apply_company_to_profile(profile, company)
        user.inn = company.inn
        user.ogrn = company.ogrn
        user.company_name = company.name_short or company.name_full
        await self.session.flush()
        return profile

    async def clear_company_profile(self, user: User) -> None:
        if self.session is None:
            raise RuntimeError("Session is required")
        profile = await self.get_user_company_profile(user.id)
        if profile is not None:
            await self.session.delete(profile)
        user.inn = None
        user.ogrn = None
        user.company_name = None
        await self.session.flush()


def _apply_company_to_profile(profile: UserCompanyProfile, company: CompanyProfileDTO) -> None:
    profile.inn = company.inn
    profile.kpp = company.kpp
    profile.ogrn = company.ogrn
    profile.name_full = company.name_full
    profile.name_short = company.name_short
    profile.company_type = company.company_type
    profile.status = company.status
    profile.address = company.address
    profile.okved = company.okved
    profile.okved_name = company.okved_name
    profile.director_name = company.director_name
    profile.registration_date = company.registration_date
    profile.source = company.source
    profile.raw_data = company.raw_data


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _company_type_label(value: Any) -> str | None:
    if value == "LEGAL":
        return "ЮЛ"
    if value == "INDIVIDUAL":
        return "ИП"
    return _string_or_none(value)


def _date_from_dadata(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    if timestamp > 10_000_000_000:
        timestamp = timestamp // 1000
    return datetime.fromtimestamp(timestamp, tz=UTC)
