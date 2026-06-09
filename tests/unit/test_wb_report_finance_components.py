from decimal import Decimal

from app.models.domain import WbDailyReportRow
from app.services.wb.reports.import_service import _finance_components_for_row


def test_wb_report_finance_components_split_amounts_by_category() -> None:
    row = WbDailyReportRow(
        id=1,
        import_id=2,
        user_id=3,
        marketplace_account_id=4,
        order_id=5,
        product_id=6,
        retail_amount=Decimal("1000"),
        for_pay=Decimal("800"),
        commission_rub=Decimal("0"),
        acceptance=Decimal("25"),
        is_active=True,
    )

    components = _finance_components_for_row(row)
    by_category = {item.finance_category: item for item in components}

    assert by_category["sale"].operation_type == "income"
    assert by_category["payout"].operation_type == "cashflow"
    assert by_category["acceptance"].original_amount == Decimal("25")
    assert by_category["commission"].original_amount == Decimal("0")


def test_storage_component_is_period_expense_without_order_fact() -> None:
    row = WbDailyReportRow(
        id=1,
        import_id=2,
        user_id=3,
        marketplace_account_id=4,
        order_id=5,
        product_id=6,
        payment_reason="Хранение",
        finance_category="storage",
        operation_scope="period",
        storage_fee=Decimal("8.22"),
        is_active=True,
    )

    components = _finance_components_for_row(row)

    assert len(components) == 1
    component = components[0]
    assert component.finance_category == "storage"
    assert component.operation_scope == "global"
    assert component.is_order_fact is False
    assert component.is_product_fact is False
    assert component.is_global_fact is True


def test_return_row_creates_return_component() -> None:
    row = WbDailyReportRow(
        id=1,
        import_id=2,
        user_id=3,
        marketplace_account_id=4,
        order_id=5,
        product_id=6,
        retail_amount=Decimal("-1000"),
        finance_category="return",
        operation_scope="order",
        is_active=True,
    )

    components = _finance_components_for_row(row)

    assert len(components) == 1
    assert components[0].finance_category == "return"
    assert components[0].normalized_amount == Decimal("-1000")
