from app.models import Base
from app.models.domain import Order as DomainOrder
from app.models.domain import Product as DomainProduct
from app.models.domain import User as DomainUser
from app.models.domain import WbDailyReportRow as DomainWbDailyReportRow
from app.models.finance import ProfitSnapshot
from app.models.orders import Order
from app.models.products import Product
from app.models.users import User
from app.models.wb_reports import WbDailyReportRow


def test_domain_compatibility_exports_match_new_modules() -> None:
    assert DomainUser is User
    assert DomainProduct is Product
    assert DomainOrder is Order
    assert DomainWbDailyReportRow is WbDailyReportRow


def test_metadata_contains_split_model_tables() -> None:
    expected_tables = {
        "users",
        "products",
        "orders",
        "profit_snapshots",
        "wb_daily_report_rows",
    }

    assert expected_tables <= set(Base.metadata.tables)
    assert ProfitSnapshot.__tablename__ == "profit_snapshots"
