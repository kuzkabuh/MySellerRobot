"""Regression tests for WB report rows linked to products without orders."""

from datetime import UTC, datetime
from decimal import Decimal

from app.models.domain import WbDailyReportRow
from app.services.wb_daily_report_import_service import (
    _resolve_order_link,
    _resolve_product_link,
    _row_reason,
    _row_status,
)
from app.services.wb_daily_report_parser import WbDailyReportParsedRow, classify_payment_reason
from app.services.common.web_orders_profit_service import _wb_fact_article_states


def _report_row(
    *,
    barcode: str | None = "2042291607481",
    nm_id: int | None = 303906114,
    supplier_article: str | None = "w4005",
    shk: str | None = "54825530647",
    srid: str | None = "39018683",
    payment_reason: str = "Возмещение издержек по перевозке/по складским операциям с товаром",
    for_pay: Decimal = Decimal("-0.71"),
) -> WbDailyReportParsedRow:
    operation_type, category = classify_payment_reason(payment_reason)
    return WbDailyReportParsedRow(
        row_number=1,
        report_type="daily",
        sale_dt=datetime(2026, 6, 7, 3, tzinfo=UTC),
        order_dt=None,
        nm_id=nm_id,
        supplier_article=supplier_article,
        product_name="Тестовый товар",
        size=None,
        barcode=barcode,
        shk=shk,
        srid=srid,
        srid_normalized=srid.lower() if srid else None,
        rid_normalized=srid.lower() if srid else None,
        doc_type_name=None,
        payment_reason=payment_reason,
        subject_name=None,
        brand_name=None,
        quantity=2,
        retail_price=None,
        retail_amount=None,
        for_pay=for_pay,
        delivery_count=None,
        return_count=None,
        delivery_rub=None,
        penalty=None,
        storage_fee=None,
        acceptance=None,
        deduction=None,
        commission_rub=None,
        commission_correction_amount=None,
        reimbursement_amount=for_pay,
        logistics_penalty_correction_type=None,
        basket_id=None,
        sale_method=None,
        finance_operation_type=operation_type,
        finance_category=category,
        order_required=True,
        raw={"for_pay": str(for_pay)},
    )


def test_report_row_with_product_but_without_order_is_partially_linked() -> None:
    row = _report_row()
    product_link = _resolve_product_link(row, {("barcode", "2042291607481"): [10]})
    order_link = _resolve_order_link(row, {})

    assert product_link.id == 10
    assert order_link.id is None
    assert _row_status(product_link, order_link) == "partial"
    assert _row_reason(product_link, order_link) == (
        "Товар найден по barcode; заказ не найден по Srid или ШК, строка учтена по товару"
    )


def test_report_row_without_order_is_not_marked_skipped_if_product_found() -> None:
    row = _report_row()
    product_link = _resolve_product_link(row, {("barcode", "2042291607481"): [10]})
    order_link = _resolve_order_link(row, {})

    assert _row_status(product_link, order_link) != "skipped"


def test_report_row_linked_to_product_by_barcode() -> None:
    row = _report_row()

    product_link = _resolve_product_link(row, {("barcode", "2042291607481"): [10]})

    assert product_link.id == 10
    assert product_link.method == "barcode"


def test_report_row_linked_to_product_by_nm_id() -> None:
    row = _report_row(barcode=None)

    product_link = _resolve_product_link(row, {("nm_id", "303906114"): [11]})

    assert product_link.id == 11
    assert product_link.method == "nm_id"


def test_report_row_linked_to_product_by_supplier_article() -> None:
    row = _report_row(barcode=None, nm_id=None)

    product_link = _resolve_product_link(row, {("supplier_article", "w4005"): [12]})

    assert product_link.id == 12
    assert product_link.method == "supplier_article"


def test_unmatched_order_row_still_used_in_product_finance() -> None:
    row = _report_row()
    product_link = _resolve_product_link(row, {("barcode", "2042291607481"): [10]})
    order_link = _resolve_order_link(row, {})

    assert product_link.id is not None
    assert _row_status(product_link, order_link) == "partial"


def test_unmatched_order_row_not_used_in_order_profit() -> None:
    row = _report_row()
    order_link = _resolve_order_link(row, {})

    assert order_link.id is None


def test_order_card_shows_missing_fact_expenses() -> None:
    states = _wb_fact_article_states(
        linked_rows=[],
        unlinked_rows=[],
        has_report_near_order=True,
    )

    assert {state.state for state in states} == {"missing"}


def test_order_card_distinguishes_zero_from_no_data() -> None:
    linked_row = WbDailyReportRow(commission_rub=Decimal("0"))

    states = _wb_fact_article_states(
        linked_rows=[linked_row],
        unlinked_rows=[],
        has_report_near_order=True,
    )

    commission = next(state for state in states if state.key == "commission")
    logistics = next(state for state in states if state.key == "logistics")
    assert commission.amount == Decimal("0")
    assert commission.state == "present"
    assert logistics.amount is None
    assert logistics.state == "missing"


def test_order_card_shows_unlinked_report_rows_for_same_product() -> None:
    unlinked_row = WbDailyReportRow(delivery_rub=Decimal("15"))

    states = _wb_fact_article_states(
        linked_rows=[],
        unlinked_rows=[unlinked_row],
        has_report_near_order=True,
    )

    logistics = next(state for state in states if state.key == "logistics")
    assert logistics.amount is None
    assert logistics.state == "unlinked"


def test_compensation_reason_is_classified_correctly() -> None:
    assert classify_payment_reason(
        "Возмещение издержек по перевозке/по складским операциям с товаром"
    ) == ("income", "compensation")


def test_compensation_negative_amount_preserves_original_sign() -> None:
    row = _report_row(for_pay=Decimal("-0.71"))

    assert row.for_pay == Decimal("-0.71")
    assert row.reimbursement_amount == Decimal("-0.71")


def test_report_import_detail_shows_partial_link_status() -> None:
    row = _report_row()
    product_link = _resolve_product_link(row, {("barcode", "2042291607481"): [10]})
    order_link = _resolve_order_link(row, {})

    assert _row_status(product_link, order_link) == "partial"
