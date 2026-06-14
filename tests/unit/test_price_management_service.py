"""Regression tests for unified price management safety rules."""

import inspect
from decimal import Decimal

from app.services.ozon.pricing.ozon_price_update_service import (
    OzonPriceUpdateItem,
    OzonPriceUpdateService,
)
from app.services.pricing.price_management_service import (
    BulkOperation,
    BulkPriceParams,
    BulkPricePreviewRow,
)
from app.web.route_modules.prices import _render_bulk_preview


def test_bulk_preview_apply_form_does_not_send_fake_account_id() -> None:
    html = _render_bulk_preview(
        [
            BulkPricePreviewRow(
                product_id=1,
                seller_article="SKU-1",
                title="Product",
                marketplace="WB",
                current_price=Decimal("100"),
                new_price=Decimal("110"),
                can_apply=True,
            )
        ],
        BulkPriceParams(operation=BulkOperation.INCREASE_PERCENT, value=Decimal("10")),
        "1",
    )

    assert 'name="marketplace_account_id" value="0"' not in html
    assert 'action="/web/prices/bulk-apply"' in html


def test_ozon_price_update_validation_uses_current_min_price() -> None:
    service = object.__new__(OzonPriceUpdateService)
    item = OzonPriceUpdateItem(product_id=1, offer_id="SKU-1", new_price=Decimal("99"))
    product = type("Product", (), {"min_price": None, "max_price": None})()

    error = service._validate(item, product, Decimal("100"))  # type: ignore[arg-type]

    assert error == "Цена 99 ниже минимальной 100"


def test_ozon_price_payload_does_not_force_zero_min_price() -> None:
    source = inspect.getsource(OzonPriceUpdateService.update_prices)

    assert '"min_price": "0"' not in source
