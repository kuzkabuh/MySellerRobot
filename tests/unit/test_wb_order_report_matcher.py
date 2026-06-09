"""Unit tests for WB order report matcher."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.domain import FinancialReportRow
from app.models.enums import Marketplace
from app.services.wb.reports.order_report_matcher import (
    MATCH_HIGH,
    MATCH_MEDIUM,
    WbOrderReportMatcher,
)


def _make_row(
    external_row_id: str = "1",
    order_external_id: str | None = "5075047440",
    srid: str | None = None,
    amount: Decimal = Decimal("1490"),
    **extra_payload: object,
) -> FinancialReportRow:
    payload = {"rrdId": int(external_row_id), "orderId": order_external_id}
    if srid:
        payload["srid"] = srid
    payload.update(extra_payload)
    return FinancialReportRow(
        id=int(external_row_id),
        user_id=10,
        marketplace_account_id=1,
        marketplace=Marketplace.WB,
        external_row_id=external_row_id,
        order_external_id=order_external_id,
        operation_type="Продажа",
        operation_category="sale",
        operation_date=datetime(2026, 3, 17, tzinfo=UTC),
        amount=amount,
        currency="RUB",
        raw_payload=payload,
    )


class TestHighPriorityMatch:
    @pytest.mark.asyncio
    async def test_exact_match_by_srid(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [42]
        mock_session.execute = AsyncMock(return_value=mock_result)

        matcher = WbOrderReportMatcher(mock_session)
        row = _make_row(srid="SRID-ABC-123")

        result = await matcher.match(row, account_id=1)

        assert result.match_status == "matched"
        assert result.match_confidence == MATCH_HIGH
        assert result.order_id == 42
        assert "srid" in result.match_method

    @pytest.mark.asyncio
    async def test_match_by_order_id(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [42]
        mock_session.execute = AsyncMock(return_value=mock_result)

        matcher = WbOrderReportMatcher(mock_session)
        row = _make_row(order_external_id="ORD-001")

        result = await matcher.match(row, account_id=1)

        assert result.match_status == "matched"
        assert result.match_method == "orderId"

    @pytest.mark.asyncio
    async def test_ambiguous_when_multiple_candidates(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [1, 2, 3]
        mock_session.execute = AsyncMock(return_value=mock_result)

        matcher = WbOrderReportMatcher(mock_session)
        row = _make_row(srid="SRID-ABC")

        result = await matcher.match(row, account_id=1)

        assert result.match_status == "ambiguous"
        assert result.candidates_count == 3

    @pytest.mark.asyncio
    async def test_unmatched_when_no_candidates(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        matcher = WbOrderReportMatcher(mock_session)
        row = _make_row(srid="SRID-NONEXISTENT")

        result = await matcher.match(row, account_id=1)

        assert result.match_status == "unmatched"


class TestLowPriorityNotAutoMatch:
    @pytest.mark.asyncio
    async def test_vendor_code_date_window_returns_manual_review(self) -> None:
        """Низкоточный матчинг (vendorCode + окно дат) не должен автоматчиться."""
        mock_session = AsyncMock()

        # High-priority returns empty
        empty = MagicMock()
        empty.scalars.return_value.all.side_effect = [[], [], []]

        mock_session.execute = AsyncMock(return_value=empty)

        matcher = WbOrderReportMatcher(mock_session)
        row = _make_row(
            external_row_id="1",
            srid=None,
            order_external_id=None,
            vendorCode="VENDOR-001",
        )

        result = await matcher.match(row, account_id=1)

        assert result.match_status == "unmatched"


class TestMediumPriority:
    @pytest.mark.asyncio
    async def test_medium_match_by_nm_id_and_amount(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [42]
        mock_session.execute = AsyncMock(return_value=mock_result)

        matcher = WbOrderReportMatcher(mock_session)
        row = _make_row(
            external_row_id="1",
            srid=None,
            order_external_id=None,
            nmId="12345678",
            sku="SKU-001",
            orderDt="2026-03-17T10:00:00Z",
            amount=1490,
        )

        result = await matcher.match(row, account_id=1)

        assert result.match_status == "matched"
        assert result.match_confidence == MATCH_MEDIUM
