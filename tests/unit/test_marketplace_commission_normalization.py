"""version: 1.2.0
description: Unit tests for WB/Ozon marketplace commission and tariff normalization.
updated: 2026-05-20
"""

from decimal import Decimal

from app.integrations.ozon import OzonClient
from app.integrations.wb import WildberriesClient
from app.models.domain import Order, OrderItem
from app.models.enums import EconomyConfidence, ExpenseSource, Marketplace, SaleModel
from app.services.marketplace_estimates import calculate_planned_economics
from app.services.product_sync_service import ProductSyncService, WbTariffRow


def test_wb_report_order_uses_commission_percent_when_amount_absent() -> None:
    order = WildberriesClient("token").normalize_report_order(
        {
            "srid": "wb-1",
            "orderDate": "2026-05-15T10:00:00Z",
            "nmID": 123,
            "supplierArticle": "SKU-1",
            "retailPriceWithDiscRub": "1000",
            "commissionPercent": "12.5",
        }
    )

    assert order.items[0].commission_estimated == Decimal("125.00")


def test_wb_report_order_uses_exact_commission_amount() -> None:
    order = WildberriesClient("token").normalize_report_order(
        {
            "srid": "wb-2",
            "orderDate": "2026-05-15T10:00:00Z",
            "nmID": 124,
            "supplierArticle": "SKU-2",
            "retailPriceWithDiscRub": "1000",
            "ppvzReward": "-180",
        }
    )

    assert order.items[0].commission_estimated == Decimal("180")


def test_ozon_order_uses_financial_commission_and_services() -> None:
    order = OzonClient("client", "key").normalize_fbo_posting(
        {
            "posting_number": "ozon-1",
            "created_at": "2026-05-15T10:00:00Z",
            "status": "delivered",
            "products": [
                {
                    "sku": 999,
                    "offer_id": "SKU-1",
                    "name": "Товар",
                    "quantity": 1,
                    "price": "1000",
                }
            ],
            "financial_data": {
                "products": [
                    {
                        "sku": 999,
                        "commission_amount": "-150",
                        "payout": "800",
                        "services": [
                            {"name": "MarketplaceServiceItemDirectFlowLogistic", "price": "-70"},
                            {"name": "MarketplaceServiceItemReturnProcessing", "price": "-20"},
                        ],
                    }
                ]
            },
        }
    )

    item = order.items[0]
    assert item.commission_estimated == Decimal("150")
    assert item.logistics_estimated == Decimal("70")
    assert item.other_marketplace_expenses_estimated == Decimal("20")


def test_product_sync_applies_per_model_wb_commission_tariff() -> None:
    product = WildberriesClient("token").normalize_card_product(
        payload={
            "nmID": 303948126,
            "vendorCode": "W4079",
            "title": "Салфетки",
            "subjectID": 99,
            "subjectName": "Салфетки для уборки",
        },
        user_id=1,
        account_id=10,
    )

    tariffs = {
        "99": WbTariffRow(
            subject_id="99",
            subject_name="Салфетки для уборки",
            parent_id="10",
            parent_name="Хозяйственные товары",
            commission_fbw=Decimal("0.2450"),
            commission_fbs=Decimal("0.2800"),
            commission_dbs=Decimal("0.2500"),
            commission_edbs=None,
            commission_pickup=None,
            commission_booking=None,
        ),
    }

    ProductSyncService._apply_wb_commission_tariff(
        product,
        {"subjectID": 99, "subjectName": "Салфетки для уборки"},
        tariffs,
    )

    assert product.marketplace_category_id == "99"
    assert product.commission_fbw == Decimal("0.2450")
    assert product.commission_fbs == Decimal("0.2800")
    assert product.commission_dbs == Decimal("0.2500")
    assert product.marketplace_commission_rate == Decimal("0.2800")
    assert product.marketplace_commission_source == "WB tariffs /api/v1/tariffs/commission"


def test_wb_fbs_order_selects_fbs_commission_not_dbs() -> None:
    """Test 1: FBS order for dish cloths must use FBS=28%, not DBS=25%."""
    order = Order(marketplace=Marketplace.WB, sale_model=SaleModel.FBS)
    item = OrderItem(discounted_price=Decimal("1000"), quantity=1)

    economics = calculate_planned_economics(
        order,
        item,
        commission_fbw=Decimal("0.2450"),
        commission_fbs=Decimal("0.2800"),
        commission_dbs=Decimal("0.2500"),
    )

    assert economics.commission == Decimal("280.00")
    assert economics.commission_rate == Decimal("0.2800")
    assert economics.commission_is_baseline is True
    assert economics.commission_source == ExpenseSource.WB_TARIFF_API


def test_wb_dbs_order_selects_dbs_commission() -> None:
    """Test 2: DBS order for the same product must use DBS=25%."""
    order = Order(marketplace=Marketplace.WB, sale_model=SaleModel.DBS)
    item = OrderItem(discounted_price=Decimal("1000"), quantity=1)

    economics = calculate_planned_economics(
        order,
        item,
        commission_fbw=Decimal("0.2450"),
        commission_fbs=Decimal("0.2800"),
        commission_dbs=Decimal("0.2500"),
    )

    assert economics.commission == Decimal("250.00")
    assert economics.commission_rate == Decimal("0.2500")
    assert economics.commission_is_baseline is True
    assert economics.commission_source == ExpenseSource.WB_TARIFF_API


def test_wb_fbw_order_selects_fbw_commission() -> None:
    """Test 3: FBW/FBO order must use paidStorageKgvp / FBW commission."""
    order = Order(marketplace=Marketplace.WB, sale_model=SaleModel.FBO)
    item = OrderItem(discounted_price=Decimal("1000"), quantity=1)

    economics = calculate_planned_economics(
        order,
        item,
        commission_fbw=Decimal("0.2450"),
        commission_fbs=Decimal("0.2800"),
        commission_dbs=Decimal("0.2500"),
    )

    assert economics.commission == Decimal("245.00")
    assert economics.commission_rate == Decimal("0.2450")
    assert economics.commission_is_baseline is True
    assert economics.commission_source == ExpenseSource.WB_TARIFF_API


def test_wb_commission_not_found_marks_preliminary() -> None:
    """Test 4: When commission for subjectID is not found, calculation is preliminary."""
    order = Order(marketplace=Marketplace.WB, sale_model=SaleModel.FBS)
    item = OrderItem(discounted_price=Decimal("1000"), quantity=1)

    economics = calculate_planned_economics(
        order,
        item,
        commission_fbw=None,
        commission_fbs=None,
        commission_dbs=None,
    )

    assert economics.commission == Decimal("0.00")
    assert economics.commission_rate is None
    assert economics.commission_is_known is False
    assert economics.confidence == EconomyConfidence.PRELIMINARY


def test_wb_fbs_order_does_not_silently_use_dbs_commission() -> None:
    """Test 4b: FBS order must NOT fall back to DBS commission when FBS is missing."""
    order = Order(marketplace=Marketplace.WB, sale_model=SaleModel.FBS)
    item = OrderItem(discounted_price=Decimal("1000"), quantity=1)

    economics = calculate_planned_economics(
        order,
        item,
        commission_fbw=None,
        commission_fbs=None,
        commission_dbs=Decimal("0.2500"),
    )

    assert economics.commission == Decimal("0.00")
    assert economics.commission_is_known is False


def test_telegram_formatter_shows_correct_commission_percent() -> None:
    """Test 5: Telegram formatter outputs correct percentage and commission amount."""
    order = Order(marketplace=Marketplace.WB, sale_model=SaleModel.FBS)
    item = OrderItem(discounted_price=Decimal("298"), quantity=1)

    economics = calculate_planned_economics(
        order,
        item,
        commission_fbs=Decimal("0.2800"),
        commission_dbs=Decimal("0.2500"),
    )

    percent = (economics.commission_rate * Decimal("100")).quantize(Decimal("1"))
    assert percent == Decimal("28")
    assert economics.commission == Decimal("83.44")


def test_wb_rfbs_order_uses_fbs_commission() -> None:
    order = Order(marketplace=Marketplace.WB, sale_model=SaleModel.RFBS)
    item = OrderItem(discounted_price=Decimal("1000"), quantity=1)

    economics = calculate_planned_economics(
        order,
        item,
        commission_fbs=Decimal("0.2800"),
        commission_dbs=Decimal("0.2500"),
    )

    assert economics.commission == Decimal("280.00")
    assert economics.commission_rate == Decimal("0.2800")


def test_wb_dbw_order_uses_dbs_commission() -> None:
    order = Order(marketplace=Marketplace.WB, sale_model=SaleModel.DBW)
    item = OrderItem(discounted_price=Decimal("1000"), quantity=1)

    economics = calculate_planned_economics(
        order,
        item,
        commission_fbs=Decimal("0.2800"),
        commission_dbs=Decimal("0.2500"),
    )

    assert economics.commission == Decimal("250.00")
    assert economics.commission_rate == Decimal("0.2500")


def test_wb_planned_economics_uses_legacy_fallback_when_no_per_model() -> None:
    order = Order(marketplace=Marketplace.WB, sale_model=SaleModel.FBS)
    item = OrderItem(discounted_price=Decimal("1000"), quantity=1)

    economics = calculate_planned_economics(
        order,
        item,
        product_commission_rate=Decimal("0.1250"),
    )

    assert economics.commission == Decimal("125.00")
    assert economics.commission_rate == Decimal("0.1250")
    assert economics.commission_is_known is True
    assert economics.commission_is_baseline is True
    assert economics.commission_source == ExpenseSource.WB_TARIFF_API
    assert economics.confidence == EconomyConfidence.PRELIMINARY


def test_wb_planned_economics_does_not_fake_unknown_commission() -> None:
    order = Order(marketplace=Marketplace.WB, sale_model=SaleModel.FBS)
    item = OrderItem(discounted_price=Decimal("1000"), quantity=1)

    economics = calculate_planned_economics(order, item)

    assert economics.commission == Decimal("0.00")
    assert economics.commission_rate is None
    assert economics.commission_is_known is False
    assert economics.confidence == EconomyConfidence.PRELIMINARY


def test_exact_economy_when_marketplace_expenses_are_fact_based() -> None:
    order = Order(marketplace=Marketplace.OZON, sale_model=SaleModel.FBO)
    item = OrderItem(
        discounted_price=Decimal("1000"),
        quantity=1,
        commission_estimated=Decimal("150"),
        logistics_estimated=Decimal("70"),
    )

    economics = calculate_planned_economics(order, item)

    assert economics.commission_source == ExpenseSource.OZON_FINANCIAL_DATA
    assert economics.logistics_source == ExpenseSource.OZON_FINANCIAL_DATA
    assert economics.confidence == EconomyConfidence.EXACT


def test_wb_fbs_fallback_logistics_is_not_exact() -> None:
    order = Order(marketplace=Marketplace.WB, sale_model=SaleModel.FBS)
    item = OrderItem(
        discounted_price=Decimal("1000"),
        quantity=1,
        commission_estimated=Decimal("120"),
        logistics_estimated=Decimal("0"),
    )

    economics = calculate_planned_economics(order, item)

    assert economics.logistics == Decimal("92.00")
    assert economics.logistics_is_known is False
    assert economics.logistics_source == ExpenseSource.FALLBACK_DEFAULT
    assert economics.confidence == EconomyConfidence.PRELIMINARY
