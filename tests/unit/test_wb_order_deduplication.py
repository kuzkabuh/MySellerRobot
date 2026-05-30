"""version: 1.0.0
description: Tests for WB order deduplication by srid, canonical order number preservation,
             Statistics API datetime parsing, and duplicate repair.
updated: 2026-05-20
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from app.integrations.wb import WildberriesClient
from app.models.domain import Order
from app.models.enums import Marketplace, SaleModel, SourceEventType

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

LIVE_ORDER_PAYLOAD = {
    "id": 5075047440,
    "rid": "eAg.i1431b91f64a560ca4d7d8aa093c321e4.0.0",
    "nmId": 303892412,
    "skus": ["2042291443904"],
    "price": 31600,
    "chrtId": 461681576,
    "article": "W4062",
    "createdAt": "2026-05-20T07:19:17Z",
    "salePrice": 45500,
    "finalPrice": 29800,
    "warehouseId": 1745949,
    "deliveryType": "fbs",
    "convertedPrice": 31600,
    "convertedFinalPrice": 29800,
}

STATISTICS_ORDER_PAYLOAD = {
    "spp": 35,
    "date": "2026-05-20T10:19:17",
    "nmId": 303892412,
    "srid": "eAg.i1431b91f64a560ca4d7d8aa093c321e4.0.0",
    "brand": "Wai Ora",
    "barcode": "2042291443904",
    "gNumber": "98512121039949664298",
    "sticker": "",
    "subject": "Салфетки для мытья посуды",
    "category": "Хозяйственные товары",
    "incomeID": 0,
    "isCancel": False,
    "isSupply": False,
    "techSize": "0",
    "cancelDate": "0001-01-01T00:00:00",
    "regionName": "Московская область",
    "totalPrice": 1820,
    "countryName": "Россия",
    "finishedPrice": 298,
    "isRealization": True,
    "priceWithDisc": 455,
    "warehouseName": "Внуково",
    "warehouseType": "Склад продавца",
    "lastChangeDate": "2026-05-20T12:14:18",
    "discountPercent": 75,
    "oblastOkrugName": "Центральный федеральный округ",
    "supplierArticle": "W4062",
}


def _make_order(
    *,
    order_id: int,
    account_id: int,
    external_id: str,
    srid: str | None,
    source: SourceEventType,
    status: str = "new",
    normalized_status: str = "new",
    requires_action: bool = False,
    warehouse: str = "",
    raw_payload: dict | None = None,
) -> Order:
    order = Order(
        user_id=1,
        marketplace_account_id=account_id,
        marketplace=Marketplace.WB,
        order_external_id=external_id,
        order_date=datetime(2026, 5, 20, 7, 19, 17, tzinfo=UTC),
        event_received_at=datetime.now(tz=UTC),
        sale_model=SaleModel.FBS,
        fulfillment_type="FBS",
        source_event_type=source,
        status=status,
        raw_status=status,
        normalized_status=normalized_status,
        warehouse=warehouse,
        warehouse_type="seller",
        delivery_schema="FBS",
        requires_seller_action=requires_action,
        srid=srid,
        raw_payload=raw_payload or {},
    )
    order.id = order_id
    order.items = []
    return order


class TestWBDeduplication:
    """Test 1: WB live order + statistics order deduplication by srid."""

    def test_live_and_statistics_have_same_srid(self) -> None:
        client = WildberriesClient("fake-key")

        live = client.normalize_fbs_order(LIVE_ORDER_PAYLOAD)
        assert live.order_external_id == "5075047440"
        assert live.srid == "eAg.i1431b91f64a560ca4d7d8aa093c321e4.0.0"
        assert live.source_event_type == SourceEventType.LIVE_ORDER

        stats = client.normalize_statistics_order(STATISTICS_ORDER_PAYLOAD)
        assert stats.srid == "eAg.i1431b91f64a560ca4d7d8aa093c321e4.0.0"
        assert stats.source_event_type == SourceEventType.STATISTICS_ORDER

        assert live.srid == stats.srid

    @pytest.mark.asyncio
    async def test_upsert_finds_existing_by_srid(self) -> None:
        from app.repositories.orders import OrderRepository

        live = WildberriesClient("fake-key").normalize_fbs_order(LIVE_ORDER_PAYLOAD)
        stats = WildberriesClient("fake-key").normalize_statistics_order(STATISTICS_ORDER_PAYLOAD)

        live_order = _make_order(
            order_id=1,
            account_id=1,
            external_id="5075047440",
            srid="eAg.i1431b91f64a560ca4d7d8aa093c321e4.0.0",
            source=SourceEventType.LIVE_ORDER,
            requires_action=True,
        )

        call_count = 0

        def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count <= 2:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            elif call_count == 3:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            elif call_count == 4:
                mock_result.scalar_one_or_none = MagicMock(return_value=live_order)
            else:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            return mock_result

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=mock_execute)
        session.flush = AsyncMock()

        repo = OrderRepository(session)

        # First call: no existing order → create (2 execute calls: external_id + srid)
        result1 = await repo.upsert(user_id=1, account_id=1, normalized=live)
        assert result1[1] is True

        # Second call: find by srid → merge.
        # Two execute calls: external_id returns None, srid finds it.
        result2 = await repo.upsert(user_id=1, account_id=1, normalized=stats)
        assert result2[1] is False
        assert result2[0].id == 1
        assert result2[0].order_external_id == "5075047440"
        assert result2[0].source_event_type == SourceEventType.LIVE_ORDER


class TestOrderNumberPreservation:
    """Test 2: Order number is never replaced by srid."""

    def test_live_order_external_id_is_real_wb_number(self) -> None:
        client = WildberriesClient("fake-key")
        order = client.normalize_fbs_order(LIVE_ORDER_PAYLOAD)
        assert order.order_external_id == "5075047440"
        assert order.order_external_id != order.srid

    def test_statistics_order_external_id_is_srid(self) -> None:
        client = WildberriesClient("fake-key")
        order = client.normalize_statistics_order(STATISTICS_ORDER_PAYLOAD)
        assert order.order_external_id == "eAg.i1431b91f64a560ca4d7d8aa093c321e4.0.0"


class TestWBDatetimeParsing:
    """Test 3: WB Statistics datetime is not shifted by +3 hours."""

    def test_orders_api_utc_time_is_correct(self) -> None:
        client = WildberriesClient("fake-key")
        order = client.normalize_fbs_order(LIVE_ORDER_PAYLOAD)

        assert order.order_date.tzinfo is not None
        utc_dt = order.order_date.astimezone(UTC)
        assert utc_dt.hour == 7
        assert utc_dt.minute == 19

        moscow_dt = order.order_date.astimezone(MOSCOW_TZ)
        assert moscow_dt.hour == 10
        assert moscow_dt.minute == 19

    def test_statistics_api_naive_datetime_is_moscow_time(self) -> None:
        client = WildberriesClient("fake-key")
        order = client.normalize_statistics_order(STATISTICS_ORDER_PAYLOAD)

        assert order.order_date.tzinfo is not None
        moscow_dt = order.order_date.astimezone(MOSCOW_TZ)
        assert moscow_dt.hour == 10
        assert moscow_dt.minute == 19

        utc_dt = order.order_date.astimezone(UTC)
        assert utc_dt.hour == 7

    def test_parse_wb_statistics_datetime_with_naive_string(self) -> None:
        client = WildberriesClient("fake-key")
        result = client._parse_wb_statistics_datetime("2026-05-20T10:19:17")
        assert result is not None
        assert result.tzinfo is not None
        assert result.tzinfo == MOSCOW_TZ

    def test_parse_wb_statistics_datetime_with_utc_string(self) -> None:
        client = WildberriesClient("fake-key")
        result = client._parse_wb_statistics_datetime("2026-05-20T07:19:17Z")
        assert result is not None
        assert result.tzinfo is not None

    def test_parse_wb_statistics_datetime_none(self) -> None:
        client = WildberriesClient("fake-key")
        assert client._parse_wb_statistics_datetime(None) is None
        assert client._parse_wb_statistics_datetime("") is None

    def test_parse_optional_date_still_treats_naive_as_utc(self) -> None:
        """_parse_optional_date (for Orders API) should still treat naive as UTC."""
        client = WildberriesClient("fake-key")
        result = client._parse_optional_date("2026-05-20T10:19:17")
        assert result is not None
        assert result.tzinfo == UTC


class TestMergeEnrichment:
    """Test enrichment of LIVE_ORDER from Statistics API."""

    @pytest.mark.asyncio
    async def test_enrichment_payload_saved(self) -> None:
        from app.repositories.orders import OrderRepository

        live = WildberriesClient("fake-key").normalize_fbs_order(LIVE_ORDER_PAYLOAD)
        stats = WildberriesClient("fake-key").normalize_statistics_order(STATISTICS_ORDER_PAYLOAD)

        live_order = _make_order(
            order_id=1,
            account_id=1,
            external_id="5075047440",
            srid="eAg.i1431b91f64a560ca4d7d8aa093c321e4.0.0",
            source=SourceEventType.LIVE_ORDER,
            requires_action=True,
            raw_payload={"id": 5075047440},
        )

        call_count = 0

        def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count <= 2:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            elif call_count == 3:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            elif call_count == 4:
                mock_result.scalar_one_or_none = MagicMock(return_value=live_order)
            else:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            return mock_result

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=mock_execute)
        session.flush = AsyncMock()

        repo = OrderRepository(session)
        await repo.upsert(user_id=1, account_id=1, normalized=live)
        await repo.upsert(user_id=1, account_id=1, normalized=stats)

        enrichment = live_order.raw_payload.get("_enrichment", {})
        assert "wb_statistics_order" in enrichment
        assert enrichment["wb_statistics_order"]["spp"] == 35
        assert enrichment["wb_statistics_order"]["brand"] == "Wai Ora"

    @pytest.mark.asyncio
    async def test_live_order_status_not_overwritten(self) -> None:
        from app.repositories.orders import OrderRepository

        live = WildberriesClient("fake-key").normalize_fbs_order(LIVE_ORDER_PAYLOAD)
        stats = WildberriesClient("fake-key").normalize_statistics_order(STATISTICS_ORDER_PAYLOAD)

        live_order = _make_order(
            order_id=1,
            account_id=1,
            external_id="5075047440",
            srid="eAg.i1431b91f64a560ca4d7d8aa093c321e4.0.0",
            source=SourceEventType.LIVE_ORDER,
            requires_action=True,
            status="new",
            normalized_status="new",
        )

        call_count = 0

        def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count <= 2:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            elif call_count == 3:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            elif call_count == 4:
                mock_result.scalar_one_or_none = MagicMock(return_value=live_order)
            else:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            return mock_result

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=mock_execute)
        session.flush = AsyncMock()

        repo = OrderRepository(session)
        await repo.upsert(user_id=1, account_id=1, normalized=live)
        await repo.upsert(user_id=1, account_id=1, normalized=stats)

        assert live_order.requires_seller_action is True
        assert live_order.source_event_type == SourceEventType.LIVE_ORDER
        assert live_order.normalized_status == "new"

    @pytest.mark.asyncio
    async def test_cancel_status_propagated(self) -> None:
        from app.repositories.orders import OrderRepository

        live = WildberriesClient("fake-key").normalize_fbs_order(LIVE_ORDER_PAYLOAD)

        cancelled_stats = dict(STATISTICS_ORDER_PAYLOAD)
        cancelled_stats["isCancel"] = True
        stats = WildberriesClient("fake-key").normalize_statistics_order(cancelled_stats)

        live_order = _make_order(
            order_id=1,
            account_id=1,
            external_id="5075047440",
            srid="eAg.i1431b91f64a560ca4d7d8aa093c321e4.0.0",
            source=SourceEventType.LIVE_ORDER,
            requires_action=True,
            status="new",
            normalized_status="new",
        )

        call_count = 0

        def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count <= 2:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            elif call_count == 3:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            elif call_count == 4:
                mock_result.scalar_one_or_none = MagicMock(return_value=live_order)
            else:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            return mock_result

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=mock_execute)
        session.flush = AsyncMock()

        repo = OrderRepository(session)
        await repo.upsert(user_id=1, account_id=1, normalized=live)
        await repo.upsert(user_id=1, account_id=1, normalized=stats)

        assert live_order.normalized_status == "cancelled"

    @pytest.mark.asyncio
    async def test_warehouse_enriched_if_technical(self) -> None:
        from app.repositories.orders import OrderRepository

        live = WildberriesClient("fake-key").normalize_fbs_order(LIVE_ORDER_PAYLOAD)
        stats = WildberriesClient("fake-key").normalize_statistics_order(STATISTICS_ORDER_PAYLOAD)

        live_order = _make_order(
            order_id=1,
            account_id=1,
            external_id="5075047440",
            srid="eAg.i1431b91f64a560ca4d7d8aa093c321e4.0.0",
            source=SourceEventType.LIVE_ORDER,
            requires_action=True,
            warehouse="1745949",
        )

        call_count = 0

        def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count <= 2:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            elif call_count == 3:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            elif call_count == 4:
                mock_result.scalar_one_or_none = MagicMock(return_value=live_order)
            else:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            return mock_result

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=mock_execute)
        session.flush = AsyncMock()

        repo = OrderRepository(session)
        await repo.upsert(user_id=1, account_id=1, normalized=live)
        assert live_order.warehouse == "1745949"

        await repo.upsert(user_id=1, account_id=1, normalized=stats)

        assert live_order.warehouse == "Внуково"


class TestSalesEventLinking:
    """Test 4: SalesEvent is linked to canonical LIVE_ORDER by srid."""

    @pytest.mark.asyncio
    async def test_get_by_external_finds_by_srid_for_wb(self) -> None:
        from app.repositories.orders import OrderRepository

        live_order = _make_order(
            order_id=1,
            account_id=1,
            external_id="5075047440",
            srid="eAg.i1431b91f64a560ca4d7d8aa093c321e4.0.0",
            source=SourceEventType.LIVE_ORDER,
            requires_action=True,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(side_effect=[None, live_order])

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        repo = OrderRepository(session)

        found = await repo.get_by_external(
            account_id=1,
            marketplace=Marketplace.WB,
            order_external_id="eAg.i1431b91f64a560ca4d7d8aa093c321e4.0.0",
        )
        assert found is not None
        assert found.id == 1
        assert found.order_external_id == "5075047440"


class TestRepairDuplicates:
    """Test 5: Repair of existing duplicates."""

    @pytest.mark.asyncio
    async def test_repair_finds_and_merges_duplicates(self) -> None:
        from app.cli.repair_wb_duplicate_orders import find_duplicates, merge_and_delete

        live_order = _make_order(
            order_id=1,
            account_id=1,
            external_id="5075047440",
            srid="eAg.i1431b91f64a560ca4d7d8aa093c321e4.0.0",
            source=SourceEventType.LIVE_ORDER,
            requires_action=True,
            raw_payload={"id": 5075047440},
        )

        stat_order = _make_order(
            order_id=2,
            account_id=1,
            external_id="eAg.i1431b91f64a560ca4d7d8aa093c321e4.0.0",
            srid="eAg.i1431b91f64a560ca4d7d8aa093c321e4.0.0",
            source=SourceEventType.STATISTICS_ORDER,
            status="statistics_order",
            normalized_status="ordered",
            requires_action=False,
            raw_payload={"spp": 35, "brand": "Wai Ora"},
        )

        mock_row = SimpleNamespace(
            live_id=1,
            live_external_id="5075047440",
            live_srid="eAg.i1431b91f64a560ca4d7d8aa093c321e4.0.0",
            live_source="LIVE_ORDER",
            stat_id=2,
            stat_external_id="eAg.i1431b91f64a560ca4d7d8aa093c321e4.0.0",
            stat_srid="eAg.i1431b91f64a560ca4d7d8aa093c321e4.0.0",
            stat_source="STATISTICS_ORDER",
            marketplace_account_id=1,
        )
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([mock_row]))

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        session.get = AsyncMock(
            side_effect=lambda model, pk: {1: live_order, 2: stat_order}.get(pk)
        )
        session.delete = AsyncMock()
        session.commit = AsyncMock()

        dups = await find_duplicates(session)
        assert len(dups) == 1

        result = await merge_and_delete(session, dups[0], dry_run=True)
        assert "enrichment_payload_merged" in result["steps"]
        assert "dry_run: no deletion" in result["steps"]

        assert live_order.order_external_id == "5075047440"
        assert live_order.raw_payload.get("_enrichment", {}).get("wb_statistics_order") is not None
