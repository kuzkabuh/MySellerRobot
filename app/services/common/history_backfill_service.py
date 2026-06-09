"""version: 1.1.0
description: Initial and manual historical marketplace data backfill service.
updated: 2026-05-15
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import TokenCipher
from app.integrations.ozon import OzonClient
from app.integrations.wb import WildberriesClient
from app.models.domain import MarketplaceAccount, OrderItem, ProfitSnapshot, SyncJob
from app.models.enums import CalculationType, Marketplace, SyncJobStatus, SyncJobType
from app.repositories.events import ReturnsEventRepository, SalesEventRepository
from app.repositories.orders import OrderRepository
from app.repositories.sync_jobs import SyncJobRepository
from app.services.unit_economics.finance_service import FinanceService
from app.services.unit_economics.order_profit_service import OrderProfitService
from app.services.common.product_sync_service import ProductSyncService
from app.services.wb.reports.operation_classifier import (
    classify_financial_operation,
    has_real_order_id,
    is_sale_operation,
)
from app.services.wb_report_relink_service import WbReportRelinkService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BackfillCounters:
    orders: int = 0
    sales: int = 0
    returns: int = 0
    financial_rows: int = 0
    profit_items: int = 0
    skipped: int = 0
    failed: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def loaded(self) -> int:
        return self.orders + self.sales + self.returns + self.financial_rows


class HistoryBackfillService:
    """Run chunked historical imports for a connected marketplace account."""

    def __init__(
        self,
        session: AsyncSession,
        cipher: TokenCipher | None = None,
        *,
        chunk_days: int | None = None,
    ) -> None:
        self.session = session
        self.cipher = cipher or TokenCipher()
        self.chunk_days = chunk_days or get_settings().backfill_chunk_days
        self.jobs = SyncJobRepository(session)
        self.orders = OrderRepository(session)
        self.sales = SalesEventRepository(session)
        self.returns = ReturnsEventRepository(session)
        self.finance = FinanceService(session)
        self.profits = OrderProfitService(session)

    async def schedule_initial(
        self,
        account: MarketplaceAccount,
        *,
        days: int = 30,
    ) -> SyncJob:
        return await self.schedule_manual(
            account,
            days=days,
            job_type=SyncJobType.INITIAL_HISTORY_BACKFILL,
        )

    async def schedule_manual(
        self,
        account: MarketplaceAccount,
        *,
        days: int = 30,
        job_type: SyncJobType = SyncJobType.MANUAL_HISTORY_BACKFILL,
    ) -> SyncJob:
        date_to = datetime.now(tz=UTC)
        date_from = date_to - timedelta(days=days)
        chunks = self.build_chunks(date_from, date_to, self.chunk_days)
        job = await self.jobs.create_history_backfill(
            account=account,
            job_type=job_type,
            date_from=date_from,
            date_to=date_to,
            total_chunks=len(chunks),
            payload={"days": days, "chunk_days": self.chunk_days},
        )
        await self.session.commit()
        return job

    async def schedule_period(
        self,
        account: MarketplaceAccount,
        *,
        date_from: datetime,
        date_to: datetime,
        job_type: SyncJobType = SyncJobType.MANUAL_HISTORY_BACKFILL,
    ) -> SyncJob:
        chunks = self.build_chunks(date_from, date_to, self.chunk_days)
        job = await self.jobs.create_history_backfill(
            account=account,
            job_type=job_type,
            date_from=date_from,
            date_to=date_to,
            total_chunks=len(chunks),
            payload={
                "source": "wb_report_import",
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "chunk_days": self.chunk_days,
            },
        )
        await self.session.commit()
        return job

    async def run_job(self, job_id: int) -> BackfillCounters:
        job = await self.jobs.get(job_id)
        if job is None:
            raise RuntimeError(f"Задача синхронизации #{job_id} не найдена.")
        account = await self.jobs.get_account(job)
        if account is None:
            raise RuntimeError(f"Кабинет для задачи #{job_id} не найден.")
        await self.jobs.mark_running(job)
        await self.session.commit()
        counters = BackfillCounters()
        metadata: dict[str, Any] = {"blocks": {}, "warnings": []}
        processed_chunks = 0
        try:
            try:
                await ProductSyncService(self.session, self.cipher).sync_account_products(account)
            except Exception as exc:
                counters.warnings.append("Не удалось полностью синхронизировать товары.")
                metadata["warnings"].append(str(exc))
                logger.exception("history_product_sync_failed", extra={"account_id": account.id})
                await self.session.rollback()

            chunks = self.build_chunks(
                self._required_dt(job.date_from),
                self._required_dt(job.date_to),
                self.chunk_days,
            )
            for chunk_from, chunk_to in chunks:
                chunk_result = await self._run_chunk(account, chunk_from, chunk_to)
                self._merge(counters, chunk_result)
                processed_chunks += 1
                metadata["blocks"] = self._block_statuses(counters)
                counters.warnings = self._unique_warnings(counters.warnings)
                metadata["warnings"] = counters.warnings
                await self.jobs.update_progress(
                    job,
                    processed_chunks=processed_chunks,
                    records_loaded=counters.loaded,
                    records_skipped=counters.skipped,
                    records_failed=counters.failed,
                    metadata=metadata,
                )
                await self.session.commit()
            status = (
                SyncJobStatus.COMPLETED_WITH_WARNINGS
                if counters.warnings or counters.failed
                else SyncJobStatus.COMPLETED
            )
            await self.jobs.mark_finished(job, status=status)
            if account.marketplace == Marketplace.WB:
                relink = await WbReportRelinkService(self.session).relink_pending_rows(
                    marketplace_account_id=account.id
                )
                metadata["wb_report_relink"] = {
                    "scanned": relink.scanned,
                    "matched": relink.matched,
                    "pending": relink.pending,
                    "ambiguous": relink.ambiguous,
                    "errors": relink.errors,
                }
                job.job_metadata = metadata
            await self.session.commit()
            return counters
        except Exception as exc:
            logger.exception("history_backfill_failed", extra={"job_id": job.id})
            await self.session.rollback()
            job = await self.jobs.get(job_id)
            if job is not None:
                await self.jobs.mark_finished(
                    job,
                    status=SyncJobStatus.FAILED,
                    error_message=str(exc),
                )
                await self.session.commit()
            raise

    async def _run_chunk(
        self,
        account: MarketplaceAccount,
        date_from: datetime,
        date_to: datetime,
    ) -> BackfillCounters:
        if account.marketplace == Marketplace.WB:
            return await self._run_wb_chunk(account, date_from, date_to)
        return await self._run_ozon_chunk(account, date_from, date_to)

    async def _run_wb_chunk(
        self,
        account: MarketplaceAccount,
        date_from: datetime,
        date_to: datetime,
    ) -> BackfillCounters:
        counters = BackfillCounters()
        client = WildberriesClient(self.cipher.decrypt(account.encrypted_api_key))
        try:
            for payload in await client.get_supplier_orders(date_from):
                if not isinstance(payload, dict):
                    continue
                event_date = self._parse_dt(payload.get("date"))
                if not (date_from <= event_date < date_to):
                    continue
                normalized = client.normalize_statistics_order(payload)
                created = await self._upsert_order_with_profit(account, normalized)
                counters.orders += int(created)
                counters.profit_items += len(normalized.items)
                counters.skipped += int(not created)
            for payload in await client.get_fbs_orders(date_from=date_from, date_to=date_to):
                if not isinstance(payload, dict):
                    continue
                normalized = client.normalize_historical_fbs_order(payload)
                created = await self._upsert_order_with_profit(account, normalized)
                counters.orders += int(created)
                counters.profit_items += len(normalized.items)
                counters.skipped += int(not created)
        except Exception:
            counters.failed += 1
            counters.warnings.append("WB FBS-заказы за часть периода загружены не полностью.")
            logger.exception("wb_history_orders_failed", extra={"account_id": account.id})
            await self.session.rollback()

        try:
            for payload in await client.get_supplier_sales(date_from):
                if not isinstance(payload, dict):
                    continue
                event = client.normalize_supplier_sale(payload)
                if not (date_from <= event.event_date < date_to):
                    continue
                created = await self.sales.add_once(
                    user_id=account.user_id,
                    account_id=account.id,
                    marketplace=Marketplace.WB,
                    external_event_id=event.external_event_id,
                    order_external_id=event.order_external_id,
                    event_date=event.event_date,
                    quantity=event.quantity,
                    amount=event.amount,
                    raw_payload=event.raw_payload,
                    event_type=event.event_type,
                    seller_article=event.seller_article,
                    marketplace_article=event.marketplace_article,
                    expected_payout=event.expected_payout,
                )
                counters.sales += int(created)
                counters.skipped += int(not created)
            data = await client.get_sales_report_details(
                date_from.date().isoformat(),
                date_to.date().isoformat(),
            )
            rows = self._extract_rows(data)
            for row in rows:
                if not isinstance(row, dict):
                    continue
                await self._store_wb_financial_row(account, row, counters)
        except Exception:
            counters.failed += 1
            counters.warnings.append("WB финансовые строки за часть периода недоступны.")
            logger.exception("wb_history_finance_failed", extra={"account_id": account.id})
            await self.session.rollback()
        return counters

    async def _run_ozon_chunk(
        self,
        account: MarketplaceAccount,
        date_from: datetime,
        date_to: datetime,
    ) -> BackfillCounters:
        counters = BackfillCounters()
        api_key = self.cipher.decrypt(account.encrypted_api_key)
        client_id = self.cipher.decrypt(account.encrypted_client_id or "")
        client = OzonClient(client_id, api_key)

        for fetcher, normalizer, warning in [
            (
                client.get_fbs_postings,
                client.normalize_fbs_posting,
                "Ozon FBS/rFBS-заказы за часть периода загружены не полностью.",
            ),
            (
                client.get_fbo_postings,
                client.normalize_fbo_posting,
                "Ozon FBO-заказы за часть периода загружены не полностью.",
            ),
        ]:
            try:
                offset = 0
                while True:
                    data = await fetcher(date_from, date_to, limit=100, offset=offset)
                    postings = self._extract_postings(data)
                    if not postings:
                        break
                    for payload in postings:
                        if not isinstance(payload, dict):
                            continue
                        normalized = normalizer(payload)
                        created = await self._upsert_order_with_profit(account, normalized)
                        counters.orders += int(created)
                        counters.profit_items += len(normalized.items)
                        counters.skipped += int(not created)
                    if len(postings) < 100:
                        break
                    offset += 100
            except Exception:
                counters.failed += 1
                counters.warnings.append(warning)
                logger.exception("ozon_history_orders_failed", extra={"account_id": account.id})
                await self.session.rollback()

        try:
            returns_data = await client.get_returns(date_from=date_from, date_to=date_to)
            for row in self._extract_rows(returns_data):
                if isinstance(row, dict):
                    created = await self._store_ozon_return(account, row)
                    counters.returns += int(created)
                    counters.skipped += int(not created)
        except Exception:
            counters.failed += 1
            counters.warnings.append("Ozon возвраты за часть периода загружены не полностью.")
            logger.exception("ozon_history_returns_failed", extra={"account_id": account.id})
            await self.session.rollback()

        counters.warnings.append(
            "Ozon финансовые отчёты импортируются отдельной задачей после формирования отчёта."
        )
        return counters

    async def _upsert_order_with_profit(self, account: MarketplaceAccount, normalized: Any) -> bool:
        order, created = await self.orders.upsert(account.user_id, account.id, normalized)
        await self.session.execute(
            delete(ProfitSnapshot).where(
                ProfitSnapshot.order_item_id.in_(self._order_item_ids_query(order.id)),
                ProfitSnapshot.calculation_type == CalculationType.ESTIMATED,
            )
        )
        await self.profits.calculate_estimated_profit(
            account,
            order,
            normalized,
            calculation_source="history_estimated",
        )
        return created

    @staticmethod
    def _order_item_ids_query(order_id: int) -> Any:
        return select(OrderItem.id).where(OrderItem.order_id == order_id)

    async def _store_wb_financial_row(
        self,
        account: MarketplaceAccount,
        row: dict[str, Any],
        counters: BackfillCounters,
    ) -> None:
        operation_date = self._parse_dt(
            row.get("saleDt") or row.get("date") or row.get("orderDate")
        )
        external_row_id = str(
            row.get("rrdId")
            or row.get("realizationreportId")
            or row.get("srid")
            or f"wb-fin-{account.id}-{operation_date.isoformat()}-{row.get('nmID')}"
        )
        amount = self._decimal(row.get("ppvzForPay") or row.get("retailPriceWithDiscRub") or 0)

        seller_oper = str(row.get("sellerOperName") or "").strip() or None
        doc_type = str(row.get("docTypeName") or "").strip() or None
        operation_type, operation_category = classify_financial_operation(
            seller_oper_name=seller_oper,
            doc_type_name=doc_type,
            bonus_type_name=str(row.get("bonusTypeName") or "").strip() or None,
        )

        added = await self.finance.add_financial_row(
            user_id=account.user_id,
            account_id=account.id,
            marketplace=Marketplace.WB,
            external_row_id=external_row_id,
            operation_type=operation_type,
            operation_date=operation_date,
            amount=amount,
            order_external_id=str(row.get("srid") or "") or None,
            product_external_id=str(row.get("nmID") or row.get("nmId") or "") or None,
            raw_payload=row,
        )
        counters.financial_rows += int(added)
        counters.skipped += int(not added)

        if operation_type == "return":
            created = await self.returns.add_once(
                user_id=account.user_id,
                account_id=account.id,
                marketplace=Marketplace.WB,
                external_event_id=f"wb-return-{external_row_id}",
                order_external_id=str(row.get("srid") or "") or None,
                event_date=operation_date,
                quantity=int(row.get("quantity") or 1),
                amount=amount,
                reason=str(row.get("bonusTypeName") or "") or None,
                raw_payload=row,
            )
            counters.returns += int(created)
            return

        if not is_sale_operation(operation_type):
            counters.skipped += 1
            return

        if not has_real_order_id(row):
            counters.skipped += 1
            return

        created = await self.sales.add_once(
            user_id=account.user_id,
            account_id=account.id,
            marketplace=Marketplace.WB,
            external_event_id=f"wb-sale-{external_row_id}",
            order_external_id=str(row.get("srid") or "") or None,
            event_date=operation_date,
            quantity=int(row.get("quantity") or 1),
            amount=amount,
            raw_payload=row,
        )
        counters.sales += int(created)

        try:
            created_order = await self._upsert_order_with_profit(
                account,
                WildberriesClient("").normalize_report_order(row),
            )
            counters.orders += int(created_order)
            counters.profit_items += int(created_order)
            counters.skipped += int(not created_order)
        except Exception:
            counters.warnings.append("Часть WB строк отчёта не удалось сопоставить с заказами.")

    async def _store_ozon_return(
        self,
        account: MarketplaceAccount,
        row: dict[str, Any],
    ) -> bool:
        event_date = self._parse_dt(
            row.get("created_at") or row.get("returned_at") or row.get("updated_at")
        )
        external_id = str(
            row.get("return_id")
            or row.get("id")
            or row.get("posting_number")
            or f"ozon-return-{account.id}-{event_date.isoformat()}"
        )
        return await self.returns.add_once(
            user_id=account.user_id,
            account_id=account.id,
            marketplace=Marketplace.OZON,
            external_event_id=external_id,
            order_external_id=str(row.get("posting_number") or "") or None,
            event_date=event_date,
            quantity=int(row.get("quantity") or 1),
            amount=self._decimal(row.get("price") or row.get("amount") or 0),
            reason=str(row.get("return_reason_name") or row.get("reason") or "") or None,
            raw_payload=row,
        )

    @staticmethod
    def build_chunks(
        date_from: datetime,
        date_to: datetime,
        chunk_days: int,
    ) -> list[tuple[datetime, datetime]]:
        chunks: list[tuple[datetime, datetime]] = []
        current = date_from
        step = timedelta(days=max(1, chunk_days))
        while current < date_to:
            chunk_to = min(current + step, date_to)
            chunks.append((current, chunk_to))
            current = chunk_to
        return chunks

    @staticmethod
    def format_started_message(days: int) -> str:
        return (
            "✅ Кабинет подключён.\n"
            f"Начинаю первичную загрузку заказов, продаж и аналитики за последние {days} дней.\n"
            "Когда данные будут готовы, бот сообщит об этом."
        )

    @staticmethod
    def format_completion_message(job: SyncJob, counters: BackfillCounters) -> str:
        title = "📊 Первичная синхронизация завершена."
        if job.status == SyncJobStatus.COMPLETED_WITH_WARNINGS:
            title = "📊 Первичная синхронизация завершена частично."
        if job.status == SyncJobStatus.FAILED:
            return (
                "❌ Первичная синхронизация не завершилась.\n\n"
                f"Причина: {job.error_message or 'техническая ошибка'}"
            )
        lines = [
            title,
            f"Маркетплейс: {HistoryBackfillService._marketplace_title(job.marketplace)}",
            "",
            "Загружено:",
            f"— заказов: {counters.orders};",
            f"— продаж: {counters.sales};",
            f"— возвратов: {counters.returns};",
            f"— финансовых строк: {counters.financial_rows};",
            f"— товаров с рассчитанной прибылью: {counters.profit_items}.",
            "",
            "Теперь доступна аналитика за загруженный период.",
        ]
        unique_warnings = HistoryBackfillService._unique_warnings(counters.warnings)
        if unique_warnings:
            lines.extend(
                [
                    "",
                    "Часть данных загружена неполно:",
                    *[f"— {item}" for item in unique_warnings[:5]],
                ]
            )
        return "\n".join(lines)

    @staticmethod
    def _extract_postings(data: dict[str, Any]) -> list[Any]:
        result = data.get("result")
        if isinstance(result, dict):
            postings = result.get("postings")
            return postings if isinstance(postings, list) else []
        return result if isinstance(result, list) else []

    @staticmethod
    def _extract_rows(data: Any) -> list[Any]:
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return []
        for key in ["rows", "items", "operations", "returns", "result", "data", "reports"]:
            value = data.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested = HistoryBackfillService._extract_rows(value)
                if nested:
                    return nested
        return []

    @staticmethod
    def _parse_dt(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if value:
            try:
                return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                pass
        return datetime.now(tz=UTC)

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        return Decimal(str(value or 0))

    @staticmethod
    def _required_dt(value: datetime | None) -> datetime:
        if value is None:
            raise RuntimeError("В задаче исторической синхронизации не указан период.")
        return value

    @staticmethod
    def _merge(target: BackfillCounters, source: BackfillCounters) -> None:
        target.orders += source.orders
        target.sales += source.sales
        target.returns += source.returns
        target.financial_rows += source.financial_rows
        target.profit_items += source.profit_items
        target.skipped += source.skipped
        target.failed += source.failed
        target.warnings = HistoryBackfillService._unique_warnings(
            [*target.warnings, *source.warnings]
        )

    @staticmethod
    def _unique_warnings(warnings: list[str]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for warning in warnings:
            if warning not in seen:
                unique.append(warning)
                seen.add(warning)
        return unique

    @staticmethod
    def _block_statuses(counters: BackfillCounters) -> dict[str, str]:
        status = "completed_with_warnings" if counters.warnings or counters.failed else "completed"
        return {
            "orders": status if counters.orders or counters.skipped else "empty",
            "sales": status if counters.sales else "empty",
            "returns": status if counters.returns else "empty",
            "financial_rows": status if counters.financial_rows else "partial",
        }

    @staticmethod
    def _marketplace_title(marketplace: Marketplace | str | None) -> str:
        if marketplace is None:
            return "не определён"
        value = marketplace.value if isinstance(marketplace, Marketplace) else str(marketplace)
        return "Wildberries" if value == Marketplace.WB.value else "Ozon"
