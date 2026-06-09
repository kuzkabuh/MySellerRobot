"""Unit tests for WB seller balance and financial reports helpers."""

from datetime import date
from decimal import Decimal

from app.models.domain import MarketplaceAccount
from app.models.enums import Marketplace
from app.services.account.account_profile_service import _apply_wb_seller_info, _decimal_or_none
from app.services.wb.reports.report_service import _date_or_none, _extract_report_rows


def test_wb_seller_info_updates_account_profile() -> None:
    account = MarketplaceAccount(
        id=1,
        user_id=10,
        marketplace=Marketplace.WB,
        name="WB",
        encrypted_api_key="encrypted",
    )

    _apply_wb_seller_info(
        account,
        {"name": "ООО Ромашка", "sid": "123456", "tin": "7700000000", "tradeMark": "Brand"},
    )

    assert account.seller_external_id == "123456"
    assert account.seller_name == "Brand"
    assert account.seller_legal_name == "ООО Ромашка"
    assert account.seller_info_payload["tin"] == "7700000000"


def test_wb_balance_decimal_parsing_is_safe() -> None:
    assert _decimal_or_none("1234.56") == Decimal("1234.56")
    assert _decimal_or_none(None) is None
    assert _decimal_or_none("bad") is None


def test_wb_reports_list_extracts_common_payload_shapes() -> None:
    row = {"reportId": 42, "period": "daily"}

    assert _extract_report_rows({"reports": [row]}) == [row]
    assert _extract_report_rows({"data": {"items": [row]}}) == [row]
    assert _extract_report_rows({}) == []


def test_wb_report_date_parsing() -> None:
    assert _date_or_none("2026-05-17") == date(2026, 5, 17)
    assert _date_or_none("bad") is None
