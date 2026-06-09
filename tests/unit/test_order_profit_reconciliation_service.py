"""Unit tests for the order profit reconciliation service."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.domain import (
    FinancialReportRow,
    MarketplaceAccount,
    Order,
    OrderItem,
    ProfitSnapshot,
)
from app.models.enums import (
    CalculationType,
    Marketplace,
    ReconciliationStatus,
    SaleModel,
    SourceEventType,
)
from app.services.unit_economics.order_profit_reconciliation_service import (
    OrderProfitReconciliationService,
    _safe_decimal,
)

ZERO = Decimal("0")


def _make_account(id: int = 1, user_id: int = 10) -> MarketplaceAccount:
    return MarketplaceAccount(
        id=id,
        user_id=user_id,
        marketplace=Marketplace.WB,
        name="WB Test",
        encrypted_api_key="encrypted_key",
    )


def _make_order(
    id: int = 1,
    account_id: int = 1,
    user_id: int = 10,
    order_external_id: str = "5075047440",
    srid: str | None = None,
) -> Order:
    return Order(
        id=id,
        user_id=user_id,
        marketplace_account_id=account_id,
        marketplace=Marketplace.WB,
        order_external_id=order_external_id,
        srid=srid,
        order_date=datetime(2026, 3, 17, 10, 0, 0, tzinfo=UTC),
        event_received_at=datetime(2026, 3, 17, 10, 0, 0, tzinfo=UTC),
        sale_model=SaleModel.FBS,
        fulfillment_type="FBS",
        status="new",
        raw_status="new",
        normalized_status="new",
        source_event_type=SourceEventType.LIVE_ORDER,
        requires_seller_action=True,
        raw_payload={},
    )


def _make_order_item(
    id: int = 1,
    order_id: int = 1,
    product_id: int | None = None,
    discounted_price: Decimal = Decimal("1490.00"),
    quantity: int = 1,
) -> OrderItem:
    return OrderItem(
        id=id,
        order_id=order_id,
        product_id=product_id,
        title="Test Product",
        seller_article="ART-001",
        marketplace_article="12345678",
        quantity=quantity,
        buyer_price=discounted_price,
        seller_price=discounted_price,
        discounted_price=discounted_price,
    )


def _make_financial_row(
    id: int = 1,
    account_id: int = 1,
    user_id: int = 10,
    external_row_id: str = "1",
    order_external_id: str = "5075047440",
    operation_type: str = "Продажа",
    operation_category: str = "sale",
    amount: Decimal = Decimal("1490"),
    for_pay: Decimal | None = None,
) -> FinancialReportRow:
    payload = {"forPay": float(for_pay) if for_pay else None, "rrdId": int(external_row_id)}
    return FinancialReportRow(
        id=id,
        user_id=user_id,
        marketplace_account_id=account_id,
        marketplace=Marketplace.WB,
        external_row_id=external_row_id,
        order_external_id=order_external_id,
        operation_type=operation_type,
        operation_category=operation_category,
        operation_date=datetime(2026, 3, 17, tzinfo=UTC),
        amount=amount,
        currency="RUB",
        raw_payload=payload,
    )


class TestSafeDecimal:
    def test_valid_number(self) -> None:
        assert _safe_decimal("123.45") == Decimal("123.45")

    def test_none_returns_zero(self) -> None:
        assert _safe_decimal(None) == ZERO

    def test_invalid_string_returns_zero(self) -> None:
        assert _safe_decimal("bad") == ZERO


class TestReconcileOrder:
    @pytest.mark.asyncio
    async def test_no_financial_rows_returns_unmatched(self) -> None:
        mock_session = AsyncMock()
        mock_all = MagicMock(all=MagicMock(return_value=[]))
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=mock_all)),
        )
        service = OrderProfitReconciliationService(mock_session)

        order = _make_order()
        result = await service.reconcile_order(order)

        assert result.reconciliation_status == ReconciliationStatus.FACT_UNMATCHED
        assert result.rows_matched == 0
        assert result.profit is None

    @pytest.mark.asyncio
    async def test_ambiguous_rows_returns_ambiguous(self) -> None:
        mock_session = AsyncMock()
        service = OrderProfitReconciliationService(mock_session)

        order = _make_order()
        # Mock that we have financial rows
        mock_rows = MagicMock()
        mock_rows.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        mock_session.execute = AsyncMock(return_value=mock_rows)

        # Mock order_repo.get_with_items
        with patch.object(service.order_repo, "get_with_items", new_callable=AsyncMock) as mock_get:
            order_with_items = _make_order()
            order_with_items.items = [_make_order_item()]
            mock_get.return_value = order_with_items

            result = await service.reconcile_order(order)

            assert result.profit is None

    @pytest.mark.asyncio
    async def test_missing_cost_returns_missing_cost_status(self) -> None:
        mock_session = AsyncMock()
        service = OrderProfitReconciliationService(mock_session)

        order = _make_order()
        item = _make_order_item(product_id=1)
        item.cost_price_used = None

        mock_rows = MagicMock()
        mock_rows.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        mock_session.execute = AsyncMock(return_value=mock_rows)

        with patch.object(service.order_repo, "get_with_items", new_callable=AsyncMock) as mock_get:
            order_with_items = _make_order()
            order_with_items.items = [item]
            mock_get.return_value = order_with_items

            result = await service.reconcile_order(order)

            assert result.reconciliation_status == ReconciliationStatus.FACT_UNMATCHED


class TestAggregateFinancialRows:
    def test_single_sale_row(self) -> None:
        mock_session = AsyncMock()
        service = OrderProfitReconciliationService(mock_session)
        item = _make_order_item()

        frows = [
            _make_financial_row(
                operation_type="Продажа",
                operation_category="sale",
                amount=Decimal("1490"),
                for_pay=Decimal("1200"),
            )
        ]

        result = service._aggregate_financial_rows(item, frows, [])

        assert result["gross_revenue"] == Decimal("1490")
        assert result["expected_payout"] == Decimal("1200")

    def test_sale_with_commission_and_logistics(self) -> None:
        mock_session = AsyncMock()
        service = OrderProfitReconciliationService(mock_session)
        item = _make_order_item()

        sale_row = _make_financial_row(
            id=1,
            external_row_id="1",
            operation_type="Продажа",
            operation_category="sale",
            amount=Decimal("1490"),
            for_pay=Decimal("1000"),
        )
        sale_row.raw_payload = {
            "forPay": 1000,
            "ppvzSalesCommission": 200,
            "deliveryService": 50,
        }

        commission_row = _make_financial_row(
            id=2,
            external_row_id="2",
            operation_type="Комиссия WB",
            operation_category="commission",
            amount=Decimal("200"),
        )
        logistics_row = _make_financial_row(
            id=3,
            external_row_id="3",
            operation_type="Логистика",
            operation_category="logistics",
            amount=Decimal("50"),
        )

        fin_rows = [sale_row, commission_row, logistics_row]
        result = service._aggregate_financial_rows(item, fin_rows, [])

        assert result["gross_revenue"] == Decimal("1490")
        assert result["marketplace_commission"] == Decimal("200")
        assert result["logistics_cost"] == Decimal("50")

    def test_for_pay_as_primary_payout(self) -> None:
        """forPay should be used as the primary payout source."""
        mock_session = AsyncMock()
        service = OrderProfitReconciliationService(mock_session)
        item = _make_order_item()

        sale_row = _make_financial_row(
            id=1,
            external_row_id="1",
            operation_type="Продажа",
            operation_category="sale",
            amount=Decimal("1490"),
            for_pay=Decimal("1200"),
        )

        result = service._aggregate_financial_rows(item, [sale_row], [])

        assert result["expected_payout"] == Decimal("1200")

    def test_payout_from_forpay_fallback(self) -> None:
        """When no forPay in category, fallback to raw_payload forPay."""
        mock_session = AsyncMock()
        service = OrderProfitReconciliationService(mock_session)
        item = _make_order_item()

        row = _make_financial_row(
            id=1,
            external_row_id="1",
            operation_type="Продажа",
            operation_category="sale",
            amount=Decimal("1490"),
            for_pay=Decimal("1100"),
        )

        result = service._aggregate_financial_rows(item, [row], [])

        assert result["expected_payout"] == Decimal("1100")


class TestProfitCalculationWithForPay:
    """Verify that forPay-based profit doesn't double-count fees."""

    def test_actual_profit_uses_forpay_without_double_subtracting(self) -> None:
        from app.schemas.profit import CostInput, ProfitInput
        from app.services.unit_economics.profit_calculator import ProfitCalculator

        calculator = ProfitCalculator()
        result = calculator.calculate(
            ProfitInput(
                gross_revenue=Decimal("1490"),
                expected_payout=Decimal("1200"),
                marketplace_commission=Decimal("200"),
                logistics_cost=Decimal("50"),
                cost=CostInput(
                    cost_price=Decimal("500"),
                    package_cost=Decimal("25"),
                    tax_rate=Decimal("0.06"),
                ),
            )
        )

        # forPay(1200) - cost_price(500) - package(25) - tax(72) = 603
        assert result.expected_payout == Decimal("1200")
        assert result.profit == Decimal("603")
        assert result.profit < result.expected_payout


class TestSnapshotUpsert:
    @pytest.mark.asyncio
    async def test_creates_new_actual_snapshot(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.flush = AsyncMock()

        service = OrderProfitReconciliationService(mock_session)
        item = _make_order_item()

        from app.schemas.profit import ProfitResult

        result = ProfitResult(
            gross_revenue=Decimal("1490"),
            expected_payout=Decimal("1200"),
            marketplace_commission=Decimal("200"),
            logistics_cost=Decimal("50"),
            acquiring_cost=Decimal("10"),
            storage_cost=Decimal("0"),
            return_cost=Decimal("0"),
            other_marketplace_costs=Decimal("30"),
            cost_price=Decimal("500"),
            package_cost=Decimal("25"),
            additional_seller_cost=Decimal("0"),
            tax_amount=Decimal("72"),
            profit=Decimal("603"),
            margin_percent=Decimal("50.25"),
        )

        snapshot = await service._upsert_actual_snapshot(item, result)

        assert snapshot.calculation_type == CalculationType.ACTUAL
        assert snapshot.profit == Decimal("603")
        assert snapshot.economy_confidence == "EXACT"
        assert snapshot.calculation_source == "order_profit_reconciliation"
        assert mock_session.add.call_count == 1

    @pytest.mark.asyncio
    async def test_updates_existing_snapshot(self) -> None:
        mock_session = AsyncMock()
        existing = ProfitSnapshot(
            id=1,
            order_item_id=1,
            calculation_type=CalculationType.ACTUAL,
            profit=Decimal("100"),
            gross_revenue=Decimal("0"),
            marketplace_commission=Decimal("0"),
            logistics_cost=Decimal("0"),
            acquiring_cost=Decimal("0"),
            storage_cost=Decimal("0"),
            return_cost=Decimal("0"),
            other_marketplace_costs=Decimal("0"),
            cost_price=Decimal("0"),
            package_cost=Decimal("0"),
            additional_seller_cost=Decimal("0"),
            tax_amount=Decimal("0"),
            margin_percent=Decimal("0"),
            calculated_at=datetime.now(tz=UTC),
            calculation_source="old",
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.flush = AsyncMock()

        service = OrderProfitReconciliationService(mock_session)
        item = _make_order_item()

        from app.schemas.profit import ProfitResult

        result = ProfitResult(
            gross_revenue=Decimal("2000"),
            expected_payout=Decimal("1600"),
            marketplace_commission=Decimal("300"),
            logistics_cost=Decimal("60"),
            acquiring_cost=Decimal("15"),
            storage_cost=Decimal("0"),
            return_cost=Decimal("0"),
            other_marketplace_costs=Decimal("40"),
            cost_price=Decimal("600"),
            package_cost=Decimal("30"),
            additional_seller_cost=Decimal("0"),
            tax_amount=Decimal("96"),
            profit=Decimal("850"),
            margin_percent=Decimal("53.12"),
        )

        snapshot = await service._upsert_actual_snapshot(item, result)

        assert mock_session.add.call_count == 0
        assert snapshot.profit == Decimal("850")
        assert snapshot.calculation_source == "order_profit_reconciliation"
