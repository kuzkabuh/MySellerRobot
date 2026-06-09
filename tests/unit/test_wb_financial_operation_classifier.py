"""Tests for WB financial operation classification.

Verifies that financial report rows are correctly classified and
that non-sale operations (compensation, logistics, storage, etc.)
do NOT create orders.
"""

from decimal import Decimal

import pytest

from app.services.wb.reports.operation_classifier import (
    SALE,
    RETURN,
    LOGISTICS,
    STORAGE,
    PENALTY,
    DEDUCTION,
    COMPENSATION,
    ADJUSTMENT,
    ACQUIRING,
    COMMISSION,
    PAID_ACCEPTANCE,
    OTHER,
    classify_financial_operation,
    has_real_order_id,
    is_order_creating_operation,
    is_sale_operation,
)


class TestClassifyFinancialOperation:
    def test_sale_by_doc_type(self) -> None:
        op_type, cat = classify_financial_operation(
            seller_oper_name=None,
            doc_type_name="Продажа",
        )
        assert op_type == SALE
        assert cat == "revenue"

    def test_sale_by_seller_oper(self) -> None:
        op_type, cat = classify_financial_operation(
            seller_oper_name="Продажа товара",
            doc_type_name=None,
        )
        assert op_type == SALE
        assert cat == "revenue"

    def test_return(self) -> None:
        op_type, cat = classify_financial_operation(
            seller_oper_name="Возврат товара",
            doc_type_name=None,
        )
        assert op_type == RETURN
        assert cat == "return"

    def test_return_by_doc_type(self) -> None:
        op_type, cat = classify_financial_operation(
            seller_oper_name=None,
            doc_type_name="Возврат",
        )
        assert op_type == RETURN

    def test_logistics(self) -> None:
        op_type, cat = classify_financial_operation(
            seller_oper_name="Логистика до склада",
            doc_type_name=None,
        )
        assert op_type == LOGISTICS
        assert cat == "logistics"

    def test_delivery(self) -> None:
        op_type, cat = classify_financial_operation(
            seller_oper_name="Стоимость доставки",
        )
        assert op_type == LOGISTICS

    def test_storage(self) -> None:
        op_type, cat = classify_financial_operation(
            seller_oper_name="Хранение товара на складе",
        )
        assert op_type == STORAGE
        assert cat == "storage"

    def test_penalty(self) -> None:
        op_type, cat = classify_financial_operation(
            seller_oper_name="Штраф за нарушение",
        )
        assert op_type == PENALTY
        assert cat == "penalty"

    def test_deduction(self) -> None:
        op_type, cat = classify_financial_operation(
            seller_oper_name="Удержание издержек",
        )
        assert op_type == DEDUCTION
        assert cat == "deduction"

    def test_paid_acceptance(self) -> None:
        op_type, cat = classify_financial_operation(
            seller_oper_name="Платная приемка FBS",
        )
        assert op_type == PAID_ACCEPTANCE
        assert cat == "paid_acceptance"

    def test_compensation(self) -> None:
        op_type, cat = classify_financial_operation(
            seller_oper_name="Компенсация за утерю товара",
        )
        assert op_type == COMPENSATION
        assert cat == "compensation"


class TestCompensationLogistics:
    def test_compensation_logistics(self) -> None:
        """Возмещение издержек по перевозке должно быть compensation, а не sale."""
        op_type, cat = classify_financial_operation(
            seller_oper_name=(
                "Возмещение издержек по перевозке/по складским операциям с товаром"
            ),
        )
        assert op_type == COMPENSATION
        assert cat == "compensation"
        assert not is_sale_operation(op_type)
        assert not is_order_creating_operation(op_type)


class TestAdjustment:
    def test_adjustment(self) -> None:
        op_type, cat = classify_financial_operation(
            seller_oper_name="Корректировка комиссии",
        )
        assert op_type == ADJUSTMENT
        assert cat == "adjustment"


class TestAcquiring:
    def test_acquiring(self) -> None:
        op_type, cat = classify_financial_operation(
            seller_oper_name="Эквайринг",
        )
        assert op_type == ACQUIRING
        assert cat == "acquiring"


class TestCommission:
    def test_commission(self) -> None:
        op_type, cat = classify_financial_operation(
            seller_oper_name="Комиссия Wildberries",
        )
        assert op_type == COMMISSION
        assert cat == "commission"

    def test_reward(self) -> None:
        op_type, cat = classify_financial_operation(
            seller_oper_name="Вознаграждение WB",
        )
        assert op_type == COMMISSION


class TestUnknown:
    def test_unknown_operation(self) -> None:
        op_type, cat = classify_financial_operation(
            seller_oper_name="Какая-то непонятная операция",
        )
        assert op_type == OTHER
        assert cat == "other"

    def test_none_operation(self) -> None:
        op_type, cat = classify_financial_operation(
            seller_oper_name=None,
            doc_type_name=None,
        )
        assert op_type == OTHER


class TestHasRealOrderId:
    def test_positive_order_id(self) -> None:
        assert has_real_order_id({"orderId": 12345}) is True

    def test_zero_order_id(self) -> None:
        assert has_real_order_id({"orderId": 0}) is False

    def test_string_positive_order_id(self) -> None:
        assert has_real_order_id({"orderId": "12345"}) is True

    def test_string_zero_order_id(self) -> None:
        assert has_real_order_id({"orderId": "0"}) is False

    def test_missing_order_id(self) -> None:
        assert has_real_order_id({"srid": "12345"}) is False

    def test_negative_order_id(self) -> None:
        assert has_real_order_id({"orderId": -1}) is False


class TestIsSaleOperation:
    def test_sale_is_sale(self) -> None:
        assert is_sale_operation(SALE) is True

    def test_return_is_not_sale(self) -> None:
        assert is_sale_operation(RETURN) is False

    def test_logistics_is_not_sale(self) -> None:
        assert is_sale_operation(LOGISTICS) is False

    def test_compensation_is_not_sale(self) -> None:
        assert is_sale_operation(COMPENSATION) is False

    def test_storage_is_not_sale(self) -> None:
        assert is_sale_operation(STORAGE) is False

    def test_penalty_is_not_sale(self) -> None:
        assert is_sale_operation(PENALTY) is False

    def test_deduction_is_not_sale(self) -> None:
        assert is_sale_operation(DEDUCTION) is False

    def test_adjustment_is_not_sale(self) -> None:
        assert is_sale_operation(ADJUSTMENT) is False

    def test_acquiring_is_not_sale(self) -> None:
        assert is_sale_operation(ACQUIRING) is False

    def test_commission_is_not_sale(self) -> None:
        assert is_sale_operation(COMMISSION) is False

    def test_paid_acceptance_is_not_sale(self) -> None:
        assert is_sale_operation(PAID_ACCEPTANCE) is False

    def test_other_is_not_sale(self) -> None:
        assert is_sale_operation(OTHER) is False


class TestIsOrderCreatingOperation:
    def test_sale_creates_order(self) -> None:
        assert is_order_creating_operation(SALE) is True

    def test_other_operations_do_not_create_order(self) -> None:
        for op in [RETURN, LOGISTICS, STORAGE, PENALTY, DEDUCTION, COMPENSATION,
                   ADJUSTMENT, ACQUIRING, COMMISSION, PAID_ACCEPTANCE, OTHER]:
            assert is_order_creating_operation(op) is False, f"{op} should not create order"


class TestConcreteExample:
    def test_specific_compensation_row(self) -> None:
        """The specific example from the bug report.

        sellerOperName = "Возмещение издержек по перевозке/по складским операциям с товаром"
        reportId = 433534920260508
        rrdId = 3122901202528
        orderId = 0
        srid = 38428850
        nmId = 303892891
        quantity = 2
        rebillLogisticCost = 0.46
        """
        row = {
            "sellerOperName": "Возмещение издержек по перевозке/по складским операциям с товаром",
            "reportId": "433534920260508",
            "rrdId": "3122901202528",
            "orderId": 0,
            "srid": "38428850",
            "nmId": "303892891",
            "quantity": 2,
            "rebillLogisticCost": 0.46,
        }

        op_type, cat = classify_financial_operation(
            seller_oper_name=row.get("sellerOperName"),
        )

        assert op_type == COMPENSATION
        assert cat == "compensation"
        assert is_order_creating_operation(op_type) is False
        assert has_real_order_id(row) is False

    def test_compensation_row_with_valid_order_id(self) -> None:
        """Even with valid orderId, compensation should not create an order."""
        row = {
            "sellerOperName": "Возмещение издержек по перевозке",
            "orderId": 12345,
            "srid": "38428850",
        }

        op_type, cat = classify_financial_operation(
            seller_oper_name=row.get("sellerOperName"),
        )

        assert op_type == COMPENSATION
        assert is_order_creating_operation(op_type) is False

    def test_real_sale_row_creates_order(self) -> None:
        """A real sale with valid orderId should create an order."""
        row = {
            "sellerOperName": "Продажа товара",
            "orderId": 12345,
            "srid": "wb-srid-abc-123",
            "nmId": "303892891",
            "quantity": 1,
            "retailAmount": 1500,
            "forPay": 1200,
        }

        op_type, cat = classify_financial_operation(
            seller_oper_name=row.get("sellerOperName"),
        )

        assert op_type == SALE
        assert is_order_creating_operation(op_type) is True
        assert has_real_order_id(row) is True

    def test_sale_row_without_order_id(self) -> None:
        """A sale row without valid orderId should still not create order.

        The op type is sale but has_real_order_id is False, so
        _store_wb_financial_row should skip order creation.
        """
        row = {
            "sellerOperName": "Продажа товара",
            "orderId": 0,
            "srid": "wb-srid-abc-123",
        }

        assert is_sale_operation(classify_financial_operation(
            seller_oper_name=row.get("sellerOperName"),
        )[0]) is True
        assert has_real_order_id(row) is False
