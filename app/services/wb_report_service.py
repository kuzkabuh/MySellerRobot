"""Wildberries financial reports metadata sync and formatting."""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, MarketplaceApiError, RateLimitError
from app.core.security import TokenCipher
from app.integrations.wb import WildberriesClient
from app.models.domain import MarketplaceAccount, WbFinancialReport, WbReportCheckState
from app.models.enums import Marketplace

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WbReportCheckResult:
    account_id: int
    period_type: str
    status: str
    reports_found: int
    error_message: str | None = None


class WbFinancialReportService:
    """Check daily and weekly WB financial reports without loading full analytics."""

    def __init__(self, session: AsyncSession, cipher: TokenCipher | None = None) -> None:
        self.session = session
        self.cipher = cipher or TokenCipher()

    async def check_account(
        self,
        account: MarketplaceAccount,
        *,
        period_type: str,
        date_from: date,
        date_to: date,
    ) -> WbReportCheckResult:
        if account.marketplace != Marketplace.WB:
            return WbReportCheckResult(account.id, period_type, "SKIPPED", 0)
        client = WildberriesClient(self.cipher.decrypt(account.encrypted_api_key))
        now = datetime.now(tz=UTC)
        try:
            payload = await client.get_sales_reports_list(
                period=period_type,
                date_from=date_from,
                date_to=date_to,
                limit=100,
                offset=0,
            )
            rows = _extract_report_rows(payload)
            for row in rows:
                await self._upsert_report(account, period_type, row, now)
            status = "FOUND" if rows else "EMPTY"
            await self._upsert_state(account, period_type, status, len(rows), None, now)
            return WbReportCheckResult(account.id, period_type, status, len(rows))
        except (AuthenticationError, RateLimitError, MarketplaceApiError) as exc:
            status = "NO_ACCESS" if isinstance(exc, AuthenticationError) else "API_ERROR"
            if isinstance(exc, RateLimitError):
                status = "RATE_LIMITED"
            message = str(exc)[:1000]
            await self._upsert_state(account, period_type, status, 0, message, now)
            logger.warning(
                "wb_financial_reports_check_failed",
                extra={"account_id": account.id, "period_type": period_type, "status": status},
            )
            return WbReportCheckResult(account.id, period_type, status, 0, message)

    async def check_recent(self, account: MarketplaceAccount) -> list[WbReportCheckResult]:
        today = datetime.now(tz=UTC).date()
        return [
            await self.check_account(
                account,
                period_type="daily",
                date_from=today - timedelta(days=7),
                date_to=today,
            ),
            await self.check_account(
                account,
                period_type="weekly",
                date_from=today - timedelta(days=35),
                date_to=today,
            ),
        ]

    async def latest_reports(
        self,
        account_id: int,
        *,
        period_type: str | None = None,
        limit: int = 10,
    ) -> list[WbFinancialReport]:
        query = select(WbFinancialReport).where(
            WbFinancialReport.marketplace_account_id == account_id
        )
        if period_type:
            query = query.where(WbFinancialReport.period_type == period_type)
        result = await self.session.execute(
            query.order_by(
                WbFinancialReport.date_to.desc(), WbFinancialReport.fetched_at.desc()
            ).limit(limit)
        )
        return list(result.scalars().all())

    async def latest_states(self, account_id: int) -> list[WbReportCheckState]:
        result = await self.session.execute(
            select(WbReportCheckState).where(
                WbReportCheckState.marketplace_account_id == account_id
            )
        )
        return list(result.scalars().all())

    async def _upsert_report(
        self,
        account: MarketplaceAccount,
        period_type: str,
        row: dict[str, Any],
        fetched_at: datetime,
    ) -> None:
        report_id = str(
            row.get("reportId") or row.get("id") or row.get("realizationreportId") or ""
        )
        if not report_id:
            report_id = f"{period_type}-{row.get('dateFrom')}-{row.get('dateTo')}"
        result = await self.session.execute(
            select(WbFinancialReport).where(
                WbFinancialReport.marketplace_account_id == account.id,
                WbFinancialReport.period_type == period_type,
                WbFinancialReport.report_id == report_id,
            )
        )
        report = result.scalar_one_or_none()
        if report is None:
            report = WbFinancialReport(
                user_id=account.user_id,
                marketplace_account_id=account.id,
                report_id=report_id,
                period_type=period_type,
                fetched_at=fetched_at,
            )
            self.session.add(report)
        report.date_from = _date_or_none(row.get("dateFrom") or row.get("date_from"))
        report.date_to = _date_or_none(row.get("dateTo") or row.get("date_to"))
        report.create_date = _datetime_or_none(row.get("createDate") or row.get("createdAt"))
        report.currency = row.get("currency")
        report.report_type = row.get("reportType") or row.get("type")
        report.retail_amount_sum = _decimal_or_none(row.get("retailAmountSum"))
        report.for_pay_sum = _decimal_or_none(row.get("forPaySum") or row.get("for_pay_sum"))
        report.delivery_service_sum = _decimal_or_none(row.get("deliveryServiceSum"))
        report.fetched_at = fetched_at
        report.raw_payload = row
        await self.session.flush()

    async def _upsert_state(
        self,
        account: MarketplaceAccount,
        period_type: str,
        status: str,
        reports_found: int,
        error_message: str | None,
        checked_at: datetime,
    ) -> None:
        result = await self.session.execute(
            select(WbReportCheckState).where(
                WbReportCheckState.marketplace_account_id == account.id,
                WbReportCheckState.period_type == period_type,
            )
        )
        state = result.scalar_one_or_none()
        if state is None:
            state = WbReportCheckState(
                user_id=account.user_id,
                marketplace_account_id=account.id,
                period_type=period_type,
            )
            self.session.add(state)
        state.status = status
        state.reports_found = reports_found
        state.last_error_message = error_message
        state.last_checked_at = checked_at
        await self.session.flush()


def _extract_report_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("reports", "data", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = value.get("reports") or value.get("items")
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    return []


def _date_or_none(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _datetime_or_none(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
