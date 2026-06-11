"""version: 1.0.0
description: ViewModel DTOs for the products section – clean data layer between services and UI.
updated: 2026-06-11
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass
class ProductListItemView:
    master_product_id: int
    title: str
    brand: str | None
    category: str | None
    image_url: str | None
    unified_sku: str

    marketplaces: list[str]
    orders_count: int
    sales_count: int
    buyout_percent: Decimal | None
    revenue: Decimal
    profit: Decimal
    margin_percent: Decimal | None
    stock_total: int

    status: str
    status_level: str  # good / bad / warn / neutral
    updated_at: datetime | None


@dataclass
class ProductSummaryView:
    orders_count: int
    sales_count: int
    buyout_percent: Decimal | None
    revenue: Decimal
    profit: Decimal
    margin_percent: Decimal | None
    stock_total: int
    avg_price: Decimal | None


@dataclass
class MarketplaceProductView:
    marketplace: str
    marketplace_label_html: str

    external_id: str
    seller_article: str
    marketplace_article: str
    title: str

    price: Decimal | None
    discounted_price: Decimal | None
    old_price: Decimal | None
    marketing_price: Decimal | None

    orders: int
    sales: int
    returns: int
    buyout_percent: Decimal | None
    revenue: Decimal
    amount_to_pay: Decimal
    cost_price: Decimal
    expenses: Decimal
    profit: Decimal
    margin_percent: Decimal | None

    stock: int
    rating: Decimal | None
    reviews: int

    commission: Decimal | None
    logistics: Decimal | None
    storage: Decimal | None
    advertising: Decimal | None
    fines: Decimal | None

    external_link: str | None
    updated_at: datetime | None
    card_status: str
    match_errors: list[str]


@dataclass
class CostHistoryView:
    valid_from: str
    valid_to: str | None
    cost_price: Decimal
    package_cost: Decimal
    additional_cost: Decimal
    total_cost: Decimal
    source: str
    comment: str | None
    created_at: str


@dataclass
class ProductFinanceView:
    total_revenue: Decimal
    total_amount_to_pay: Decimal
    total_commission: Decimal
    total_logistics: Decimal
    total_storage: Decimal
    total_advertising: Decimal
    total_fines: Decimal
    total_returns: Decimal
    total_cost_price: Decimal
    total_packaging: Decimal
    total_add_cost: Decimal
    net_profit: Decimal
    margin_percent: Decimal | None
    roi_percent: Decimal | None

    wb: dict | None = None
    ozon: dict | None = None


@dataclass
class ProductPriceHistoryView:
    date: str
    marketplace: str
    price: Decimal | None
    discounted_price: Decimal | None
    old_price: Decimal | None
    source: str
    comment: str | None


@dataclass
class ProductStockHistoryView:
    date: str
    marketplace: str
    warehouse: str | None
    quantity: int
    reserved: int | None
    available: int | None
    updated_at: str | None


@dataclass
class ProductOrderView:
    order_id: int
    date: str
    marketplace: str
    order_number: str
    status: str
    price: Decimal
    quantity: int
    amount_to_pay: Decimal | None
    profit: Decimal | None


@dataclass
class ProductIssueView:
    level: str  # bad / warn / info
    description: str
    how_to_fix: str
    action_url: str | None = None
    action_label: str | None = None


@dataclass
class MasterProductKpiView:
    orders_count: int = 0
    sales_count: int = 0
    buyout_percent: Decimal | None = None
    revenue: Decimal = field(default_factory=lambda: Decimal("0"))
    profit: Decimal = field(default_factory=lambda: Decimal("0"))
    margin_percent: Decimal | None = None
    stock_total: int = 0
    avg_price: Decimal | None = None
    products_total: int = 0
    matched_count: int = 0
    missing_cost_count: int = 0
    negative_profit_count: int = 0
    no_stock_count: int = 0
    data_issue_count: int = 0
    needs_attention_count: int = 0


@dataclass
class ProductDetailView:
    master_product_id: int
    title: str
    brand: str | None
    category: str | None
    image_url: str | None
    unified_sku: str
    status: str
    status_level: str
    updated_at: datetime | None

    summary: ProductSummaryView
    marketplaces: list[MarketplaceProductView] = field(default_factory=list)
    finance: ProductFinanceView | None = None
    prices: list[ProductPriceHistoryView] = field(default_factory=list)
    stocks: list[ProductStockHistoryView] = field(default_factory=list)
    costs: list[CostHistoryView] = field(default_factory=list)
    orders: list[ProductOrderView] = field(default_factory=list)
    issues: list[ProductIssueView] = field(default_factory=list)
