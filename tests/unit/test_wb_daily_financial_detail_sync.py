"""Unit tests for WB daily financial detail sync service."""

from datetime import UTC, date, datetime
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
from app.models.enums import CalculationType, Marketplace, SaleModel, SourceEventType
from app.schemas.profit import CostInput, ProfitInput
from app.services.wb_daily_financial_detail_service import (
    DETAILED_REPORT_FIELDS,
    SyncCounters,
    WbDailyFinancialDetailService,
    _safe_decimal,
)


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


def _make_snapshot(
    id: int = 1,
    order_item_id: int = 1,
    calculation_type: CalculationType = CalculationType.ACTUAL,
    profit: Decimal = Decimal("0"),
) -> ProfitSnapshot:
    return ProfitSnapshot(
        id=id,
        order_item_id=order_item_id,
        calculation_type=calculation_type,
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
        profit=profit,
        margin_percent=Decimal("0"),
        calculated_at=datetime.now(tz=UTC),
        calculation_source="test",
    )


class TestSafeDecimal:
    def test_valid_number(self) -> None:
        assert _safe_decimal("123.45") == Decimal("123.45")

    def test_none_returns_zero(self) -> None:
        assert _safe_decimal(None) == Decimal("0")

    def test_invalid_string_returns_zero(self) -> None:
        assert _safe_decimal("bad") == Decimal("0")

    def test_integer_returns_decimal(self) -> None:
        assert _safe_decimal(100) == Decimal("100")


class TestExtractRows:
    def test_list_payload(self) -> None:
        service = WbDailyFinancialDetailService(AsyncMock())
        rows = [{"rrdId": 1}, {"rrdId": 2}]
        assert service._extract_rows(rows) == rows

    def test_dict_with_data_key(self) -> None:
        service = WbDailyFinancialDetailService(AsyncMock())
        payload = {"data": [{"rrdId": 1}]}
        assert service._extract_rows(payload) == [{"rrdId": 1}]

    def test_dict_with_details_key(self) -> None:
        service = WbDailyFinancialDetailService(AsyncMock())
        payload = {"details": [{"rrdId": 1}, {"rrdId": 2}]}
        assert len(service._extract_rows(payload)) == 2

    def test_empty_payload(self) -> None:
        service = WbDailyFinancialDetailService(AsyncMock())
        assert service._extract_rows(None) == []
        assert service._extract_rows({}) == []

    def test_dict_with_nested_rows(self) -> None:
        service = WbDailyFinancialDetailService(AsyncMock())
        payload = {"result": {"rows": [{"rrdId": 42}]}}
        assert service._extract_rows(payload) == [{"rrdId": 42}]


class TestGetLastRrdId:
    def test_returns_last_rrd_id(self) -> None:
        rows = [{"rrdId": 100}, {"rrdId": 200}, {"rrdId": 300}]
        assert WbDailyFinancialDetailService._get_last_rrd_id(rows) == 300

    def test_returns_none_for_empty(self) -> None:
        assert WbDailyFinancialDetailService._get_last_rrd_id([]) is None

    def test_skips_invalid_rrd_id(self) -> None:
        rows = [{"rrdId": None}, {"rrdId": "abc"}, {"rrdId": 50}]
        assert WbDailyFinancialDetailService._get_last_rrd_id(rows) == 50


class TestOperationType:
    def test_doc_type_name(self) -> None:
        result = WbDailyFinancialDetailService._determine_operation_type(
            {"docTypeName": "Продажа"},
        )
        assert result == "Продажа"

    def test_seller_oper_name_fallback(self) -> None:
        result = WbDailyFinancialDetailService._determine_operation_type(
            {"sellerOperName": "Логистика"},
        )
        assert result == "Логистика"

    def test_bonus_type_fallback(self) -> None:
        result = WbDailyFinancialDetailService._determine_operation_type(
            {"bonusTypeName": "Штраф"},
        )
        assert result == "Штраф"

    def test_unknown_fallback(self) -> None:
        assert WbDailyFinancialDetailService._determine_operation_type({}) == "unknown"


class TestAmountDetermination:
    def test_sale_amount(self) -> None:
        row = {"retailAmount": 1500}
        assert WbDailyFinancialDetailService._determine_amount(row, "Продажа") == Decimal("1500")

    def test_return_amount(self) -> None:
        row = {"returnAmount": 500}
        assert WbDailyFinancialDetailService._determine_amount(row, "Возврат") == Decimal("500")

    def test_logistics_amount(self) -> None:
        row = {"deliveryAmount": 100}
        assert WbDailyFinancialDetailService._determine_amount(row, "Логистика") == Decimal("100")

    def test_penalty_amount(self) -> None:
        row = {"penalty": 50}
        assert WbDailyFinancialDetailService._determine_amount(row, "Штраф") == Decimal("50")

    def test_storage_amount(self) -> None:
        row = {"paidStorage": 30}
        assert WbDailyFinancialDetailService._determine_amount(row, "Хранение") == Decimal("30")

    def test_deduction_amount(self) -> None:
        row = {"deduction": 20}
        assert WbDailyFinancialDetailService._determine_amount(row, "Удержание") == Decimal("20")

    def test_acceptance_amount(self) -> None:
        row = {"paidAcceptance": 15}
        op_type = "\u041f\u0440\u0438\u0451\u043c\u043a\u0430"
        assert WbDailyFinancialDetailService._determine_amount(row, op_type) == Decimal("15")

    def test_additional_payment_amount(self) -> None:
        row = {"additionalPayment": 100}
        assert WbDailyFinancialDetailService._determine_amount(row, "Доплата") == Decimal("100")

    def test_acquiring_amount(self) -> None:
        row = {"acquiringFee": 10}
        assert WbDailyFinancialDetailService._determine_amount(row, "Эквайринг") == Decimal("10")

    def test_commission_amount(self) -> None:
        row = {"ppvzSalesCommission": 200}
        assert WbDailyFinancialDetailService._determine_amount(row, "Комиссия") == Decimal("200")

    def test_for_pay_fallback(self) -> None:
        row = {"forPay": 1200}
        assert WbDailyFinancialDetailService._determine_amount(row, "unknown") == Decimal("1200")

    def test_retail_amount_fallback(self) -> None:
        row = {"retailAmount": 1500}
        assert WbDailyFinancialDetailService._determine_amount(row, "unknown") == Decimal("1500")

    def test_zero_fallback(self) -> None:
        assert WbDailyFinancialDetailService._determine_amount({}, "unknown") == Decimal("0")


class TestPagination:
    @pytest.mark.asyncio
    async def test_fetches_all_pages(self) -> None:
        mock_session = AsyncMock()
        mock_cipher = MagicMock()
        mock_cipher.decrypt = MagicMock(return_value="test_key")
        service = WbDailyFinancialDetailService(mock_session, cipher=mock_cipher)

        page1 = [{"rrdId": 1, "orderId": 100, "docTypeName": "Sale", "retailAmount": 1000}]
        page2 = [{"rrdId": 2, "orderId": 101, "docTypeName": "Sale", "retailAmount": 2000}]
        page3 = []

        call_count = 0

        async def mock_get_report(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return page1
            elif call_count == 2:
                return page2
            return page3

        account = _make_account()
        with patch.object(service, "_upsert_report_rows", new_callable=AsyncMock):
            with patch.object(service, "_reconcile_and_calculate", new_callable=AsyncMock):
                with patch(
                    "app.services.wb_daily_financial_detail_service.WildberriesClient"
                ) as MockClient:
                    mock_client = MagicMock()
                    mock_client.get_sales_report_details = mock_get_report
                    MockClient.return_value = mock_client

                    counters = await service.sync_account_for_date(
                        account,
                        date(2026, 3, 17),
                    )

        assert call_count == 3
        assert counters.pages_fetched == 3
        assert counters.total_rows_fetched == 2


class TestUpsertReportRow:
    @pytest.mark.asyncio
    async def test_upsert_new_row(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.flush = AsyncMock()

        service = WbDailyFinancialDetailService(mock_session)
        account = _make_account()
        row = {
            "rrdId": 42,
            "orderId": 5075047440,
            "nmId": 12345678,
            "docTypeName": "Продажа",
            "retailAmount": 1500,
            "forPay": 1200,
            "orderDt": "2026-03-17T10:00:00Z",
        }

        await service._upsert_single_row(account, row, "2026-03-17")

        assert mock_session.add.call_count == 1
        added_row = mock_session.add.call_args[0][0]
        assert isinstance(added_row, FinancialReportRow)
        assert added_row.external_row_id == "42"
        assert added_row.order_external_id == "5075047440"
        assert added_row.product_external_id == "12345678"
        assert added_row.operation_type == "Продажа"
        assert added_row.amount == Decimal("1500")

    @pytest.mark.asyncio
    async def test_upsert_existing_row_updates(self) -> None:
        mock_session = AsyncMock()
        existing_row = FinancialReportRow(
            id=1,
            user_id=10,
            marketplace_account_id=1,
            marketplace=Marketplace.WB,
            external_row_id="42",
            amount=Decimal("0"),
            operation_type="unknown",
            operation_date=datetime.now(tz=UTC),
            raw_payload={},
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_row
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.flush = AsyncMock()

        service = WbDailyFinancialDetailService(mock_session)
        account = _make_account()
        row = {
            "rrdId": 42,
            "orderId": 5075047440,
            "nmId": 12345678,
            "docTypeName": "Продажа",
            "retailAmount": 1500,
            "orderDt": "2026-03-17T10:00:00Z",
        }

        await service._upsert_single_row(account, row, "2026-03-17")

        assert mock_session.add.call_count == 0
        assert existing_row.amount == Decimal("1500")
        assert existing_row.operation_type == "Продажа"


class TestOrderMatching:
    @pytest.mark.asyncio
    async def test_match_by_order_id(self) -> None:
        mock_session = AsyncMock()
        service = WbDailyFinancialDetailService(mock_session)
        account = _make_account()
        order = _make_order(order_external_id="5075047440")

        mock_repo_result = MagicMock()
        mock_repo_result.scalar_one_or_none.return_value = order
        mock_session.execute = AsyncMock(return_value=mock_repo_result)

        cache: dict[str, Order] = {}
        row = {"orderId": 5075047440, "rrdId": 1}

        result = await service._find_matching_order(account, row, cache)

        assert result is not None
        assert result.id == order.id
        assert "5075047440" in cache

    @pytest.mark.asyncio
    async def test_match_by_srid(self) -> None:
        mock_session = AsyncMock()
        service = WbDailyFinancialDetailService(mock_session)
        account = _make_account()
        order = _make_order(order_external_id="5075047440", srid="eAg.i1431test")

        first_result = MagicMock()
        first_result.scalar_one_or_none.return_value = None
        second_result = MagicMock()
        second_result.scalar_one_or_none.return_value = order

        call_count = 0

        async def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return first_result
            return second_result

        mock_session.execute = mock_execute

        cache: dict[str, Order] = {}
        row = {"orderId": 9999999999, "srid": "eAg.i1431test", "rrdId": 1}

        result = await service._find_matching_order(account, row, cache)

        assert result is not None
        assert result.id == order.id

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self) -> None:
        mock_session = AsyncMock()
        service = WbDailyFinancialDetailService(mock_session)
        account = _make_account()

        no_result = MagicMock()
        no_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=no_result)

        cache: dict[str, Order] = {}
        row = {"orderId": 9999999999, "rrdId": 1}

        result = await service._find_matching_order(account, row, cache)

        assert result is None


class TestActualProfitCalculation:
    def test_aggregate_single_sale_row(self) -> None:
        mock_session = AsyncMock()
        service = WbDailyFinancialDetailService(mock_session)
        item = _make_order_item()

        rows = [
            {
                "rrdId": 1,
                "docTypeName": "Продажа",
                "retailAmount": 1490,
                "forPay": 1200,
                "ppvzSalesCommission": 200,
                "acquiringFee": 10,
            }
        ]

        aggregated = service._aggregate_report_rows(rows, item)

        assert aggregated["gross_revenue"] == Decimal("1490")
        assert aggregated["expected_payout"] == Decimal("1200")
        assert aggregated["marketplace_commission"] == Decimal("200")
        assert aggregated["acquiring_cost"] == Decimal("10")

    def test_aggregate_multiple_rows_for_one_order(self) -> None:
        mock_session = AsyncMock()
        service = WbDailyFinancialDetailService(mock_session)
        item = _make_order_item()

        rows = [
            {
                "rrdId": 1,
                "docTypeName": "Продажа",
                "retailAmount": 1490,
                "forPay": 1000,
                "ppvzSalesCommission": 200,
            },
            {
                "rrdId": 2,
                "docTypeName": "Логистика",
                "deliveryAmount": 50,
            },
            {
                "rrdId": 3,
                "docTypeName": "Штраф",
                "penalty": 30,
            },
            {
                "rrdId": 4,
                "docTypeName": "Хранение",
                "paidStorage": 10,
            },
        ]

        aggregated = service._aggregate_report_rows(rows, item)

        assert aggregated["gross_revenue"] == Decimal("1490")
        assert aggregated["marketplace_commission"] == Decimal("200")
        assert aggregated["logistics_cost"] == Decimal("50")
        assert aggregated["other_marketplace_costs"] == Decimal("30")
        assert aggregated["storage_cost"] == Decimal("10")
        assert aggregated["expected_payout"] == Decimal("1000")

    def test_actual_profit_uses_for_pay_without_double_subtracting_wb_costs(self) -> None:
        mock_session = AsyncMock()
        service = WbDailyFinancialDetailService(mock_session)
        item = _make_order_item()

        rows = [
            {
                "rrdId": 1,
                "docTypeName": "Продажа",
                "retailAmount": 1490,
                "forPay": 1000,
                "ppvzSalesCommission": 200,
                "deliveryService": 50,
                "penalty": 30,
            }
        ]

        aggregated = service._aggregate_report_rows(rows, item)
        result = service.calculator.calculate(
            ProfitInput(
                gross_revenue=aggregated["gross_revenue"],
                expected_payout=aggregated["expected_payout"],
                marketplace_commission=aggregated["marketplace_commission"],
                logistics_cost=aggregated["logistics_cost"],
                other_marketplace_costs=aggregated["other_marketplace_costs"],
                cost=CostInput(cost_price=Decimal("400"), package_cost=Decimal("25")),
            )
        )

        assert result.expected_payout == Decimal("1000.00")
        assert result.profit == Decimal("575.00")

    def test_aggregate_with_return(self) -> None:
        mock_session = AsyncMock()
        service = WbDailyFinancialDetailService(mock_session)
        item = _make_order_item()

        rows = [
            {
                "rrdId": 1,
                "docTypeName": "Продажа",
                "retailAmount": 1490,
                "forPay": 1200,
            },
            {
                "rrdId": 2,
                "docTypeName": "Возврат",
                "returnAmount": 1490,
                "retailAmount": 1490,
                "forPay": -1200,
            },
        ]

        aggregated = service._aggregate_report_rows(rows, item)

        assert aggregated["gross_revenue"] == Decimal("0")
        assert aggregated["expected_payout"] == Decimal("0")
        assert aggregated["return_cost"] == Decimal("1490")


class TestSnapshotUpsert:
    @pytest.mark.asyncio
    async def test_creates_new_actual_snapshot(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        service = WbDailyFinancialDetailService(mock_session)
        item = _make_order_item()
        counters = SyncCounters()

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
            profit=Decimal("643"),
            margin_percent=Decimal("53.58"),
        )

        await service._upsert_actual_snapshot(item, result, counters)

        assert mock_session.add.call_count == 1
        added_snapshot = mock_session.add.call_args[0][0]
        assert isinstance(added_snapshot, ProfitSnapshot)
        assert added_snapshot.calculation_type == CalculationType.ACTUAL
        assert added_snapshot.profit == Decimal("643")
        assert added_snapshot.economy_confidence == "EXACT"
        assert added_snapshot.calculation_source == "wb_daily_financial_detail"
        assert counters.snapshots_upserted == 1

    @pytest.mark.asyncio
    async def test_updates_existing_actual_snapshot(self) -> None:
        mock_session = AsyncMock()
        existing_snapshot = _make_snapshot(profit=Decimal("100"))
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_snapshot
        mock_session.execute = AsyncMock(return_value=mock_result)

        service = WbDailyFinancialDetailService(mock_session)
        item = _make_order_item()
        counters = SyncCounters()

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
            profit=Decimal("900"),
            margin_percent=Decimal("56.25"),
        )

        await service._upsert_actual_snapshot(item, result, counters)

        assert mock_session.add.call_count == 0
        assert existing_snapshot.profit == Decimal("900")
        assert existing_snapshot.gross_revenue == Decimal("2000")
        assert counters.snapshots_upserted == 1


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_repeated_sync_does_not_create_duplicates(self) -> None:
        mock_session = AsyncMock()
        service = WbDailyFinancialDetailService(mock_session)
        account = _make_account()

        report_row = {
            "rrdId": 42,
            "orderId": 5075047440,
            "nmId": 12345678,
            "docTypeName": "Продажа",
            "retailAmount": 1500,
            "forPay": 1200,
            "ppvzSalesCommission": 200,
            "orderDt": "2026-03-17T10:00:00Z",
        }

        existing_row = FinancialReportRow(
            id=1,
            user_id=10,
            marketplace_account_id=1,
            marketplace=Marketplace.WB,
            external_row_id="42",
            amount=Decimal("1500"),
            operation_type="Продажа",
            operation_date=datetime.now(tz=UTC),
            raw_payload=report_row,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_row
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.flush = AsyncMock()

        await service._upsert_single_row(account, report_row, "2026-03-17")

        assert mock_session.add.call_count == 0
        assert existing_row.amount == Decimal("1500")


class TestWorkerCronRegistration:
    def test_task_is_in_functions_list(self) -> None:
        from app.workers.settings import WorkerSettings

        func_names = [f.__name__ for f in WorkerSettings.functions]
        assert "sync_wb_daily_financial_details" in func_names

    def test_task_has_cron_schedule(self) -> None:
        from app.workers.settings import WorkerSettings

        cron_names = []
        for cron_job in WorkerSettings.cron_jobs:
            if hasattr(cron_job, "coroutine"):
                cron_names.append(cron_job.coroutine.__name__)

        assert "sync_wb_daily_financial_details" in cron_names


class TestDetailedReportFields:
    def test_fields_list_is_not_empty(self) -> None:
        assert len(DETAILED_REPORT_FIELDS) > 20

    def test_fields_contain_critical_identifiers(self) -> None:
        assert "rrdId" in DETAILED_REPORT_FIELDS
        assert "orderId" in DETAILED_REPORT_FIELDS
        assert "srid" in DETAILED_REPORT_FIELDS
        assert "nmId" in DETAILED_REPORT_FIELDS

    def test_fields_contain_critical_financial(self) -> None:
        assert "retailAmount" in DETAILED_REPORT_FIELDS
        assert "forPay" in DETAILED_REPORT_FIELDS
        assert "ppvzSalesCommission" in DETAILED_REPORT_FIELDS
        assert "acquiringFee" in DETAILED_REPORT_FIELDS
        assert "deliveryAmount" in DETAILED_REPORT_FIELDS
        assert "penalty" in DETAILED_REPORT_FIELDS
        assert "paidStorage" in DETAILED_REPORT_FIELDS
