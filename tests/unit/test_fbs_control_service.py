"""version: 1.0.0
description: Unit tests for FBS control formatting.
updated: 2026-05-14
"""

from datetime import UTC, datetime

from app.models.domain import Order
from app.models.enums import Marketplace, SaleModel
from app.services.fbs_control_service import FbsControlService


def test_format_deadline_alert() -> None:
    order = Order(
        user_id=1,
        marketplace_account_id=1,
        marketplace=Marketplace.OZON,
        order_external_id="123",
        order_date=datetime(2026, 5, 14, tzinfo=UTC),
        event_received_at=datetime(2026, 5, 14, tzinfo=UTC),
        sale_model=SaleModel.FBS,
        status="awaiting_packaging",
        deadline_at=datetime(2026, 5, 14, 17, 0, tzinfo=UTC),
        raw_payload={},
    )

    text = FbsControlService(session=None).format_deadline_alert([order])  # type: ignore[arg-type]

    assert "Риск просрочки FBS" in text
    assert "123" in text
