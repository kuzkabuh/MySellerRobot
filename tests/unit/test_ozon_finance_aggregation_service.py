"""Tests for OzonFinanceAggregationService."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, sentinel

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Marketplace, ReconciliationStatus
from app.services.ozon.finance.ozon_finance_aggregation_service import (
    OzonFinanceAggregationService,
)


@pytest.fixture
def session() -> AsyncMock:
    s = AsyncMock(spec=AsyncSession)
    s.execute = AsyncMock()
    s.flush = AsyncMock()
    s.add = MagicMock()
    return s


@pytest.fixture
def service(session: AsyncMock) -> OzonFinanceAggregationService:
    return OzonFinanceAggregationService(session)


def _make_order(
    order_id: int = 1,
    marketplace: Marketplace = Marketplace.OZON,
    order_external_id: str = "test-posting-123",
) -> MagicMock:
    order = MagicMock()
    order.id = order_id
    order.marketplace = marketplace
    order.order_external_id = order_external_id
    order.user_id = 42
    order.marketplace_account_id = 7
    order.order_date = datetime(2026, 6, 1, tzinfo=UTC)
    return order


def _mock_execute(session: AsyncMock, items: list) -> None:
    """Set up session.execute to return items for aggregation.
    Uses MagicMock (not AsyncMock) to avoid coroutine issues with .scalars().all().
    """
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    exec_mock = MagicMock()
    exec_mock.scalars.return_value = scalars_mock
    exec_mock.scalar_one_or_none.return_value = None
    session.execute.return_value = exec_mock


def _mock_execute_with_existing(session: AsyncMock, items: list) -> None:
    """Set up session.execute with existing row (for dedup test)."""
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    exec_mock = MagicMock()
    exec_mock.scalars.return_value = scalars_mock
    existing = MagicMock()
    exec_mock.scalar_one_or_none.return_value = existing
    session.execute.return_value = exec_mock


def _make_order_item(
    item_id: int = 1,
    order_id: int = 1,
    buyer_price: Decimal = Decimal("1000"),
    payout: Decimal = Decimal("850"),
    commission: Decimal = Decimal("100"),
    logistics: Decimal = Decimal("30"),
    other_expenses: Decimal = Decimal("20"),
) -> MagicMock:
    item = MagicMock()
    item.id = item_id
    item.order_id = order_id
    item.marketplace_article = "sku-001"
    item.seller_article = "art-001"
    item.title = "Test Product"
    item.quantity = 1
    item.buyer_price = buyer_price
    item.payout_amount_estimated = payout
    item.seller_payout_estimated = payout
    item.commission_estimated = commission
    item.logistics_estimated = logistics
    item.other_marketplace_expenses_estimated = other_expenses
    item.ozon_commission_base_price = buyer_price
    return item


class TestAggregateOrderFinance:
    async def test_skips_non_ozon_order(self, service: OzonFinanceAggregationService) -> None:
        order = _make_order(marketplace=Marketplace.WB)
        result = await service.aggregate_order_finance(order)
        assert result == 0

    async def test_skips_order_without_external_id(
        self, service: OzonFinanceAggregationService
    ) -> None:
        order = _make_order(order_external_id="")
        result = await service.aggregate_order_finance(order)
        assert result == 0

    async def test_skips_order_without_items(self, service, session) -> None:
        order = _make_order()
        _mock_execute(session, [])
        result = await service.aggregate_order_finance(order)
        assert result == 0

    async def test_creates_financial_rows_for_item(self, service, session) -> None:
        order = _make_order()
        item = _make_order_item()
        _mock_execute(session, [item])

        result = await service.aggregate_order_finance(order)

        # 1 sale row + 1 payout + 1 commission + 1 logistics + 1 other = 5
        assert result == 5
        assert session.add.call_count == 5

    async def test_skips_existing_rows(self, service, session) -> None:
        order = _make_order()
        item = _make_order_item()
        _mock_execute_with_existing(session, [item])

        result = await service.aggregate_order_finance(order)
        assert result == 0
        session.add.assert_not_called()

    async def test_creates_correct_row_categories(self, service, session) -> None:
        order = _make_order()
        item = _make_order_item()
        _mock_execute(session, [item])

        await service.aggregate_order_finance(order)

        calls = session.add.call_args_list
        categories = {call[0][0].operation_category for call in calls}
        assert categories == {"payout", "commission", "logistics", "other_marketplace_costs", "sale"}

    async def test_handles_missing_financial_data(self, service, session) -> None:
        order = _make_order()
        item = _make_order_item(buyer_price=Decimal("0"), payout=Decimal("0"), commission=None, logistics=None, other_expenses=None)
        _mock_execute(session, [item])

        result = await service.aggregate_order_finance(order)
        # No financial data → no rows (only sale, but gross_revenue=0 since buyer_price is 0)
        assert result == 0
        session.add.assert_not_called()


class TestReconcileOzonOrder:
    async def test_skips_non_ozon(self, service) -> None:
        order = _make_order(marketplace=Marketplace.WB)
        result = await service.reconcile_ozon_order(order)
        assert result is None
