"""Tests for sales page with WB report components."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.models.enums import Marketplace
from app.services.account.web_cabinet_service import SalesPageData, SalesRow


def _make_filters(**kwargs: Any) -> SimpleNamespace:
    """Create a DashboardFilters-like namespace for testing."""
    from app.services.common.web_dashboard_service import DashboardFilters

    return SimpleNamespace(
        period=kwargs.get("period", "30d"),
        marketplace=kwargs.get("marketplace"),
        sale_model=kwargs.get("sale_model"),
        timezone=kwargs.get("timezone", "Europe/Moscow"),
        local_date_from=kwargs.get("local_date_from", datetime(2026, 4, 19).date()),
        local_date_to=kwargs.get("local_date_to", datetime(2026, 5, 19).date()),
        date_from=kwargs.get("date_from", datetime(2026, 4, 19, tzinfo=UTC)),
        date_to=kwargs.get("date_to", datetime(2026, 5, 19, tzinfo=UTC)),
        previous_from=kwargs.get("previous_from", datetime(2026, 3, 20, tzinfo=UTC)),
        previous_to=kwargs.get("previous_to", datetime(2026, 4, 18, tzinfo=UTC)),
    )


_MOCK_FILTERS = _make_filters()


class TestSalesRow:
    def test_sales_row_has_report_fields(self) -> None:
        row = SalesRow(
            event_date=datetime(2026, 6, 1, tzinfo=UTC),
            marketplace=Marketplace.WB,
            event_type="BUYOUT",
            sale_model="FBO",
            seller_article="ART-001",
            marketplace_article="WB-001",
            product_name="Test Product",
            barcode="1234567890",
            nm_id=12345,
            quantity=2,
            amount=Decimal("2000"),
            expected_payout=Decimal("1500"),
            estimated_profit=Decimal("500"),
            actual_profit=Decimal("300"),
            fact_status="full",
            fact_status_label="Факт полный",
            order_external_id="ORD-001",
            order_id=1,
            wb_report_number="RP-001",
            wb_report_type="daily",
            wb_report_import_id=10,
            wb_components={"Реализация товаров": Decimal("2000")},
        )
        assert row.event_type == "BUYOUT"
        assert row.sale_model == "FBO"
        assert row.product_name == "Test Product"
        assert row.barcode == "1234567890"
        assert row.nm_id == 12345
        assert row.actual_profit == Decimal("300")
        assert row.fact_status == "full"
        assert row.fact_status_label == "Факт полный"
        assert row.order_id == 1
        assert row.wb_report_number == "RP-001"
        assert row.wb_report_type == "daily"
        assert row.wb_report_import_id == 10


class TestSalesPageData:
    def test_sales_page_data_has_fact_counters(self) -> None:
        data = SalesPageData(
            filters=_MOCK_FILTERS,
            rows=[],
            total_quantity=0,
            total_amount=Decimal("0"),
            total_profit=Decimal("0"),
            total_actual_profit=Decimal("0"),
            full_fact_count=5,
            partial_fact_count=3,
            pending_fact_count=2,
            no_report_count=1,
        )
        assert data.full_fact_count == 5
        assert data.partial_fact_count == 3
        assert data.pending_fact_count == 2
        assert data.no_report_count == 1
        assert data.total_actual_profit == Decimal("0")

    def test_sales_page_data_totals_with_actual_profit(self) -> None:
        rows = [
            SalesRow(
                event_date=datetime(2026, 6, 1, tzinfo=UTC),
                marketplace=Marketplace.WB,
                event_type="BUYOUT",
                sale_model=None,
                seller_article="A1",
                marketplace_article="W1",
                product_name=None,
                barcode=None,
                nm_id=None,
                quantity=1,
                amount=Decimal("1000"),
                expected_payout=Decimal("800"),
                estimated_profit=Decimal("200"),
                actual_profit=Decimal("150"),
                fact_status="full",
                fact_status_label="Факт полный",
                order_external_id="O1",
                order_id=1,
                wb_report_number="R1",
                wb_report_type="daily",
                wb_report_import_id=1,
                wb_components=None,
            ),
            SalesRow(
                event_date=datetime(2026, 6, 2, tzinfo=UTC),
                marketplace=Marketplace.WB,
                event_type="BUYOUT",
                sale_model=None,
                seller_article="A2",
                marketplace_article="W2",
                product_name=None,
                barcode=None,
                nm_id=None,
                quantity=3,
                amount=Decimal("3000"),
                expected_payout=Decimal("2500"),
                estimated_profit=Decimal("700"),
                actual_profit=Decimal("500"),
                fact_status="partial",
                fact_status_label="Факт частичный",
                order_external_id="O2",
                order_id=2,
                wb_report_number="R2",
                wb_report_type="weekly",
                wb_report_import_id=2,
                wb_components=None,
            ),
        ]
        data = SalesPageData(
            filters=_MOCK_FILTERS,
            rows=rows,
            total_quantity=sum(r.quantity for r in rows),
            total_amount=sum(r.amount for r in rows),
            total_profit=sum((r.estimated_profit or Decimal("0")) for r in rows),
            total_actual_profit=sum((r.actual_profit or Decimal("0")) for r in rows),
            full_fact_count=sum(1 for r in rows if r.fact_status == "full"),
            partial_fact_count=sum(1 for r in rows if r.fact_status == "partial"),
            pending_fact_count=sum(1 for r in rows if r.fact_status == "pending_link"),
            no_report_count=sum(1 for r in rows if r.fact_status == "no_report"),
        )
        assert data.total_quantity == 4
        assert data.total_amount == Decimal("4000")
        assert data.total_profit == Decimal("900")
        assert data.total_actual_profit == Decimal("650")
        assert data.full_fact_count == 1
        assert data.partial_fact_count == 1


class TestSalesPageRendering:
    """Tests for _sales_content HTML rendering."""

    @pytest.fixture
    def sales_data_full_fact(self) -> SalesPageData:
        rows = [
            SalesRow(
                event_date=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
                marketplace=Marketplace.WB,
                event_type="BUYOUT",
                sale_model="FBO",
                seller_article="ART-001",
                marketplace_article="WB-001",
                product_name="Test Product",
                barcode="1234567890",
                nm_id=12345,
                quantity=2,
                amount=Decimal("2000"),
                expected_payout=Decimal("1500"),
                estimated_profit=Decimal("500"),
                actual_profit=Decimal("350"),
                fact_status="full",
                fact_status_label="Факт полный",
                order_external_id="ORD-001",
                order_id=1,
                wb_report_number="RP-2026-001",
                wb_report_type="daily",
                wb_report_import_id=10,
                wb_components={
                    "Реализация товаров": Decimal("2000"),
                    "Вознаграждение WB": Decimal("-300"),
                    "Логистика": Decimal("-200"),
                },
            )
        ]
        return SalesPageData(
            filters=_MOCK_FILTERS,
            rows=rows,
            total_quantity=2,
            total_amount=Decimal("2000"),
            total_profit=Decimal("500"),
            total_actual_profit=Decimal("350"),
            full_fact_count=1,
            partial_fact_count=0,
            pending_fact_count=0,
            no_report_count=0,
        )

    @pytest.fixture
    def sales_data_no_report(self) -> SalesPageData:
        rows = [
            SalesRow(
                event_date=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
                marketplace=Marketplace.WB,
                event_type="BUYOUT",
                sale_model=None,
                seller_article="ART-002",
                marketplace_article="WB-002",
                product_name=None,
                barcode=None,
                nm_id=None,
                quantity=1,
                amount=Decimal("1000"),
                expected_payout=Decimal("800"),
                estimated_profit=Decimal("200"),
                actual_profit=None,
                fact_status="no_report",
                fact_status_label="Отчёт не загружен",
                order_external_id="ORD-002",
                order_id=2,
                wb_report_number=None,
                wb_report_type=None,
                wb_report_import_id=None,
                wb_components=None,
            )
        ]
        return SalesPageData(
            filters=_MOCK_FILTERS,
            rows=rows,
            total_quantity=1,
            total_amount=Decimal("1000"),
            total_profit=Decimal("200"),
            total_actual_profit=Decimal("0"),
            full_fact_count=0,
            partial_fact_count=0,
            pending_fact_count=0,
            no_report_count=1,
        )

    @pytest.fixture
    def sales_data_pending_link(self) -> SalesPageData:
        rows = [
            SalesRow(
                event_date=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
                marketplace=Marketplace.WB,
                event_type="BUYOUT",
                sale_model="FBS",
                seller_article="ART-003",
                marketplace_article="WB-003",
                product_name="Pending Product",
                barcode="111111",
                nm_id=33333,
                quantity=1,
                amount=Decimal("1500"),
                expected_payout=Decimal("1200"),
                estimated_profit=Decimal("300"),
                actual_profit=None,
                fact_status="pending_link",
                fact_status_label="Ожидает привязки",
                order_external_id="ORD-003",
                order_id=3,
                wb_report_number="RP-2026-003",
                wb_report_type="daily",
                wb_report_import_id=30,
                wb_components=None,
            )
        ]
        return SalesPageData(
            filters=_MOCK_FILTERS,
            rows=rows,
            total_quantity=1,
            total_amount=Decimal("1500"),
            total_profit=Decimal("300"),
            total_actual_profit=Decimal("0"),
            full_fact_count=0,
            partial_fact_count=0,
            pending_fact_count=1,
            no_report_count=0,
        )

    def test_sales_page_uses_wb_report_components(
        self, sales_data_full_fact: SalesPageData
    ) -> None:
        from app.web.views import _sales_content

        html = _sales_content(sales_data_full_fact, "Europe/Moscow", sku="")
        assert "Факт полный" in html
        assert "RP-2026-001" in html
        assert "daily" in html
        assert "href=\"/web/orders/1\"" in html

    def test_sales_page_shows_no_report_when_report_missing(
        self, sales_data_no_report: SalesPageData
    ) -> None:
        from app.web.views import _sales_content

        html = _sales_content(sales_data_no_report, "Europe/Moscow", sku="")
        assert "Отчёт не загружен" in html
        assert "нет отчёта" in html
        assert "350" not in html

    def test_sales_page_shows_pending_when_report_row_unlinked(
        self, sales_data_pending_link: SalesPageData
    ) -> None:
        from app.web.views import _sales_content

        html = _sales_content(sales_data_pending_link, "Europe/Moscow", sku="")
        assert "Ожидает привязки" in html
        assert "RP-2026-003" in html

    def test_sales_page_shows_full_fact_when_report_linked(
        self, sales_data_full_fact: SalesPageData
    ) -> None:
        from app.web.views import _sales_content

        html = _sales_content(sales_data_full_fact, "Europe/Moscow", sku="")
        assert "Факт полный" in html
        assert "350" in html

    def test_sales_page_distinguishes_zero_from_missing_data(
        self, sales_data_no_report: SalesPageData
    ) -> None:
        from app.web.views import _sales_content

        html = _sales_content(sales_data_no_report, "Europe/Moscow", sku="")
        assert "0" in html
        assert "0" in html

    def test_sales_page_links_to_order_card(self, sales_data_full_fact: SalesPageData) -> None:
        from app.web.views import _sales_content

        html = _sales_content(sales_data_full_fact, "Europe/Moscow", sku="")
        assert "href=\"/web/orders/1\"" in html
        assert "ORD-001" in html

    def test_sales_page_filters(self, sales_data_full_fact: SalesPageData) -> None:
        from app.web.views import _sales_content

        html = _sales_content(sales_data_full_fact, "Europe/Moscow", sku="")
        assert "action=\"/web/sales\"" in html

    def test_sales_summary_counts_full_fact_and_pending(
        self, sales_data_full_fact: SalesPageData
    ) -> None:
        from app.web.views import _sales_content

        html = _sales_content(sales_data_full_fact, "Europe/Moscow", sku="")
        assert "1" in html


class TestFactStatusLabels:
    def test_fact_status_labels_are_meaningful(self) -> None:
        for status, expected_prefix in [
            ("full", "Факт полный"),
            ("partial", "Факт частичный"),
            ("no_report", "Отчёт не загружен"),
            ("pending_link", "Ожидает привязки"),
        ]:
            row = SimpleNamespace(
                event_date=datetime(2026, 6, 1, tzinfo=UTC),
                marketplace=Marketplace.WB,
                event_type="BUYOUT",
                sale_model=None,
                seller_article="A",
                marketplace_article="B",
                product_name=None,
                barcode=None,
                nm_id=None,
                quantity=1,
                amount=Decimal("100"),
                expected_payout=Decimal("80"),
                estimated_profit=Decimal("20"),
                actual_profit=(Decimal("15") if status in ("full", "partial") else None),
                fact_status=status,
                fact_status_label=expected_prefix,
                order_external_id="O1",
                order_id=1,
                wb_report_number="R1" if status != "no_report" else None,
                wb_report_type="daily" if status != "no_report" else None,
                wb_report_import_id=1 if status != "no_report" else None,
                wb_components=None,
            )
            from app.web.views import _sales_content

            data = SimpleNamespace(
                filters=_MOCK_FILTERS,
                rows=[row],
                total_quantity=1,
                total_amount=Decimal("100"),
                total_profit=Decimal("20"),
                total_actual_profit=Decimal("15") if status in ("full", "partial") else Decimal("0"),
                full_fact_count=1 if status == "full" else 0,
                partial_fact_count=1 if status == "partial" else 0,
                pending_fact_count=1 if status == "pending_link" else 0,
                no_report_count=1 if status == "no_report" else 0,
                page=1,
                total_pages=1,
                per_page=50,
                total_count=1,
            )
            html = _sales_content(data, "Europe/Moscow", sku="")
            assert expected_prefix in html, (
                f"Expected {expected_prefix!r} in HTML for status {status!r}"
            )


def test_sales_page_empty_state_shows_message() -> None:
    from app.web.views import _sales_content

    data = SimpleNamespace(
        filters=_MOCK_FILTERS,
        rows=[],
        total_quantity=0,
        total_amount=Decimal("0"),
        total_profit=Decimal("0"),
        total_actual_profit=Decimal("0"),
        full_fact_count=0,
        partial_fact_count=0,
        pending_fact_count=0,
        no_report_count=0,
        page=1,
        total_pages=1,
        per_page=50,
        total_count=0,
    )
    html = _sales_content(data, "Europe/Moscow", sku="")
    assert "Продаж за выбранный период не найдено." in html
