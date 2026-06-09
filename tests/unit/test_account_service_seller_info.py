"""version: 1.0.0
description: Unit tests for marketplace seller metadata normalization.
updated: 2026-05-17
"""

from app.models.enums import Marketplace
from app.services.account.account_service import _SellerInfo


def test_ozon_seller_info_normalization() -> None:
    info = _SellerInfo.from_payload(
        Marketplace.OZON,
        {"result": {"company_id": 777, "name": "Ozon Store", "legal_name": "ООО Тест"}},
    )

    assert info.external_id == "777"
    assert info.name == "Ozon Store"
    assert info.legal_name == "ООО Тест"


def test_wb_seller_info_normalization() -> None:
    info = _SellerInfo.from_payload(
        Marketplace.WB,
        {"supplierID": 123, "tradeMark": "WB Store", "fullName": "ИП Тест"},
    )

    assert info.external_id == "123"
    assert info.name == "WB Store"
    assert info.legal_name == "ИП Тест"
