"""version: 1.0.0
description: Unit tests for cost history selection.
updated: 2026-05-14
"""

from datetime import UTC, datetime
from decimal import Decimal

from app.models.domain import ProductCostHistory
from app.services.cost_service import choose_actual_cost


def test_choose_actual_cost_by_order_date() -> None:
    old = ProductCostHistory(
        product_id=1,
        cost_price=Decimal("100"),
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        valid_to=datetime(2026, 5, 1, tzinfo=UTC),
    )
    new = ProductCostHistory(
        product_id=1,
        cost_price=Decimal("150"),
        valid_from=datetime(2026, 5, 1, tzinfo=UTC),
        valid_to=None,
    )

    actual = choose_actual_cost([old, new], datetime(2026, 5, 14, tzinfo=UTC))

    assert actual is new
