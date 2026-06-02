"""Tests for DaData company lookup service."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.models.domain import UserCompanyProfile
from app.services import company_lookup_service as service_module
from app.services.company_lookup_service import (
    LOOKUP_UNAVAILABLE_MESSAGE,
    CompanyLookupError,
    CompanyLookupService,
    CompanyProfileDTO,
    DadataNotConfiguredError,
    map_dadata_party_to_company_profile,
    normalize_inn,
    validate_inn,
)


def test_normalize_inn_removes_spaces_and_dashes() -> None:
    assert normalize_inn(" 7707-083 893 ") == "7707083893"


def test_validate_inn_accepts_valid_10_digit_organization_inn() -> None:
    assert validate_inn("7707083893") is True


def test_validate_inn_accepts_valid_12_digit_individual_inn() -> None:
    assert validate_inn("500100732259") is True


def test_validate_inn_rejects_invalid_inn() -> None:
    assert validate_inn("123") is False
    assert validate_inn("7707083894") is False


def test_map_dadata_party_to_company_profile() -> None:
    payload = {
        "value": "ООО Тест",
        "unrestricted_value": "Общество с ограниченной ответственностью Тест",
        "data": {
            "inn": "7707083893",
            "kpp": "770701001",
            "ogrn": "1027700132195",
            "type": "LEGAL",
            "name": {"short": "ООО Тест", "full": "Общество с ограниченной ответственностью Тест"},
            "state": {"status": "ACTIVE", "registration_date": 1_700_000_000_000},
            "address": {"unrestricted_value": "г Москва, ул Тестовая, д 1"},
            "okved": "62.01",
            "okved_name": "Разработка компьютерного программного обеспечения",
            "management": {"name": "Иванов Иван Иванович"},
        },
    }

    company = map_dadata_party_to_company_profile(payload)

    assert company.inn == "7707083893"
    assert company.company_type == "ЮЛ"
    assert company.status == "ACTIVE"
    assert company.registration_date == datetime.fromtimestamp(1_700_000_000, tz=UTC)
    assert company.raw_data == payload


@pytest.mark.asyncio
async def test_fetch_company_by_inn_returns_clear_error_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(
        service_module,
        "get_settings",
        lambda: SimpleNamespace(
            dadata_api_key=SecretStr(""),
            dadata_secret_key=SecretStr(""),
            dadata_base_url="https://example.test",
        ),
    )

    with pytest.raises(DadataNotConfiguredError, match=LOOKUP_UNAVAILABLE_MESSAGE):
        await CompanyLookupService().fetch_company_by_inn("7707083893")


@pytest.mark.asyncio
async def test_save_company_profile_uses_current_user_id_only() -> None:
    class FakeResult:
        def scalar_one_or_none(self):
            return None

    class FakeSession:
        def __init__(self) -> None:
            self.added: UserCompanyProfile | None = None
            self.flushed = False

        async def execute(self, _stmt):
            return FakeResult()

        def add(self, value):
            self.added = value

        async def flush(self):
            self.flushed = True

    session = FakeSession()
    user = SimpleNamespace(id=42, inn=None, ogrn=None, company_name=None)
    company = CompanyProfileDTO(
        inn="7707083893",
        ogrn="1027700132195",
        name_short="ООО Тест",
        raw_data={"safe": "payload"},
    )

    profile = await CompanyLookupService(session).save_company_profile(user, company)

    assert profile.user_id == 42
    assert session.added is profile
    assert session.flushed is True
    assert user.inn == "7707083893"
    assert user.company_name == "ООО Тест"


@pytest.mark.asyncio
async def test_fetch_company_by_inn_requires_exact_match(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"suggestions": [{"data": {"inn": "7707083893"}}]}

    class FakeClient:
        def __init__(self, *, timeout):
            assert timeout == 15

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        service_module,
        "get_settings",
        lambda: SimpleNamespace(
            dadata_api_key=SecretStr("token"),
            dadata_secret_key=SecretStr("secret"),
            dadata_base_url="https://example.test",
        ),
    )
    monkeypatch.setattr(service_module.httpx, "AsyncClient", FakeClient)

    with pytest.raises(CompanyLookupError, match="не найдены"):
        await CompanyLookupService().fetch_company_by_inn("500100732259")
