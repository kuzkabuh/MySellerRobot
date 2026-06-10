"""Compatibility exports for legacy app.models.domain imports."""

from app.models.audit import (
    ApiKeyAuditLog,
    AuditLog,
    UserActivityLog,
)
from app.models.base import Base, TimestampMixin, int_pk
from app.models.finance import (
    AccountBalanceSnapshot,
    FinancialReportRow,
    PlanFactTarget,
    ProfitSnapshot,
)
from app.models.integrations import (
    ApiRequestLog,
    SyncJob,
    SyncRun,
    SyncStatus,
    SyncTaskRun,
)
from app.models.marketplaces import (
    MarketplaceAccount,
    MarketplaceWarehouse,
)
from app.models.notifications import (
    AlertEvent,
    AlertRule,
    NotificationEvent,
    NotificationSetting,
)
from app.models.orders import (
    FboDigestQueue,
    Order,
    OrderItem,
    ReturnsEvent,
    SalesEvent,
)
from app.models.ozon_reports import (
    OzonPriceSnapshot,
    OzonPromo,
    OzonPromoProduct,
)
from app.models.products import (
    MasterProduct,
    MasterProductLink,
    Product,
    ProductCostHistory,
    StockSnapshot,
    WbProductPrice,
)
from app.models.reports import (
    DailyReport,
    MrcImport,
    MrcImportRow,
)
from app.models.settings import (
    MrcPricingSettings,
)
from app.models.users import (
    OneTimeLoginToken,
    SupportTicket,
    SupportTicketEvent,
    User,
    UserCompanyProfile,
    UserWebSession,
)
from app.models.wb_reports import (
    WbAutoPromoFileImport,
    WbAutoPromoFileImportRow,
    WbAutoPromoPriceRecommendation,
    WbAutoPromotionCondition,
    WbDailyReportImport,
    WbDailyReportImportRowLog,
    WbDailyReportRow,
    WbFinancialReport,
    WbPriceChangeHistory,
    WbPromotion,
    WbPromotionNomenclature,
    WbReportCheckState,
    WbReportFinanceComponent,
)

__all__ = [
    "Base",
    "TimestampMixin",
    "int_pk",
    "User",
    "UserCompanyProfile",
    "OneTimeLoginToken",
    "UserWebSession",
    "SupportTicket",
    "SupportTicketEvent",
    "MarketplaceAccount",
    "MarketplaceWarehouse",
    "Product",
    "MasterProduct",
    "MasterProductLink",
    "ProductCostHistory",
    "StockSnapshot",
    "WbProductPrice",
    "Order",
    "OrderItem",
    "SalesEvent",
    "ReturnsEvent",
    "FboDigestQueue",
    "ProfitSnapshot",
    "FinancialReportRow",
    "AccountBalanceSnapshot",
    "PlanFactTarget",
    "DailyReport",
    "MrcImport",
    "MrcImportRow",
    "WbFinancialReport",
    "WbReportCheckState",
    "WbPromotion",
    "WbPromotionNomenclature",
    "WbAutoPromotionCondition",
    "WbAutoPromoFileImport",
    "WbAutoPromoFileImportRow",
    "WbAutoPromoPriceRecommendation",
    "WbPriceChangeHistory",
    "WbDailyReportImport",
    "WbDailyReportRow",
    "WbReportFinanceComponent",
    "WbDailyReportImportRowLog",
    "OzonPriceSnapshot",
    "OzonPromo",
    "OzonPromoProduct",
    "NotificationSetting",
    "AlertRule",
    "AlertEvent",
    "NotificationEvent",
    "SyncJob",
    "SyncRun",
    "ApiRequestLog",
    "SyncTaskRun",
    "SyncStatus",
    "AuditLog",
    "ApiKeyAuditLog",
    "UserActivityLog",
    "MrcPricingSettings",
]
