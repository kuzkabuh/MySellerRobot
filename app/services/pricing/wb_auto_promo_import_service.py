"""version: 1.0.0
description: Excel import service for WB auto promotion conditions.
    Imports entry price conditions from user-uploaded Excel files.
updated: 2026-05-22
"""

import logging
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    Product,
    WbAutoPromotionCondition,
)

logger = logging.getLogger(__name__)

COLUMN_MAP_RU = {
    "nmid": "wb_nm_id",
    "артикул продавца": "seller_article",
    "название товара": "title",
    "название автоакции": "promotion_name",
    "цена для участия": "required_price",
    "текущая цена wb": "current_wb_price",
    "участвует": "is_participating",
    "комментарий": "comment",
}

COLUMN_MAP_TECH = {
    "wb_nm_id": "wb_nm_id",
    "seller_article": "seller_article",
    "title": "title",
    "promotion_name": "promotion_name",
    "required_price": "required_price",
    "current_wb_price": "current_wb_price",
    "is_participating": "is_participating",
    "comment": "comment",
}

REQUIRED_COLUMNS = {"wb_nm_id", "required_price"}


@dataclass(slots=True)
class AutoPromoImportPreview:
    import_id: int
    user_id: int
    marketplace_account_id: int
    total_rows: int
    valid_rows: int
    warning_rows: int
    error_rows: int
    source: str = "web"
    original_file_name: str | None = None
    created_at: datetime | None = None


@dataclass(slots=True)
class AutoPromoImportRow:
    id: int
    import_id: int
    wb_nm_id: int | None
    seller_article: str | None
    title: str | None
    promotion_name: str | None
    required_price: Decimal | None
    current_wb_price: Decimal | None
    is_participating: bool | None
    product_id: int | None
    status: str
    message: str | None


class WbAutoPromoImportService:
    """Import auto promotion conditions from Excel files."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def generate_template(self, user_id: int) -> Path:
        """Generate an Excel template for auto promotion conditions import."""
        wb = Workbook()
        ws = wb.active
        ws.title = "Условия автоакций"

        headers = [
            "nmID",
            "Артикул продавца",
            "Название товара",
            "Название автоакции",
            "Цена для участия",
            "Текущая цена WB",
            "Участвует",
            "Комментарий",
        ]
        ws.append(headers)

        ws.append([
            345455998,
            "ARTICLE-001",
            "Пример товара",
            "Автоакция WB",
            980,
            1000,
            "нет",
            "Пример строки",
        ])

        tmp = Path(tempfile.gettempdir()) / f"auto_promo_template_{user_id}.xlsx"
        wb.save(str(tmp))
        return tmp

    async def create_preview(
        self,
        file_path: Path,
        user_id: int,
        marketplace_account_id: int,
        source: str = "web",
        original_file_name: str | None = None,
    ) -> AutoPromoImportPreview:
        """Parse Excel file and create a preview of import results."""
        logger.info(
            "wb_auto_promo_conditions_import_started",
            extra={
                "user_id": user_id,
                "marketplace_account_id": marketplace_account_id,
                "file": original_file_name or file_path.name,
            },
        )

        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)

        raw_headers = next(rows_iter, None)
        if raw_headers is None:
            wb.close()
            raise ValueError("Файл пустой")

        headers = self._resolve_headers(raw_headers)
        missing = REQUIRED_COLUMNS - set(headers.values())
        if missing:
            wb.close()
            raise ValueError(f"Нет обязательных колонок: {', '.join(missing)}")

        preview_rows: list[dict[str, Any]] = []
        valid_count = 0
        warning_count = 0
        error_count = 0

        products_cache: dict[int, Product] = {}

        for row_idx, row_values in enumerate(rows_iter, start=2):
            row_data: dict[str, Any] = {}
            for idx, header_key in enumerate(headers):
                if idx < len(row_values):
                    row_data[header_key] = row_values[idx]

            wb_nm_id = self._parse_int(row_data.get("wb_nm_id"))
            required_price = self._parse_decimal(row_data.get("required_price"))
            current_wb_price = self._parse_decimal(row_data.get("current_wb_price"))
            is_participating = self._parse_bool(row_data.get("is_participating"))
            seller_article = str(row_data.get("seller_article") or "").strip()
            title = str(row_data.get("title") or "").strip()
            promotion_name = str(row_data.get("promotion_name") or "").strip()

            status = "valid"
            message: str | None = None

            if wb_nm_id is None:
                status = "error"
                message = "nmID не указан или некорректен"
                error_count += 1
            elif required_price is None or required_price <= 0:
                status = "error"
                message = "Цена для участия не указана или <= 0"
                error_count += 1
            else:
                product = await self._find_product_by_nm_id(
                    marketplace_account_id, wb_nm_id, products_cache,
                )
                if product is None:
                    status = "warning"
                    message = "Товар не найден в базе, условие будет сохранено"
                    warning_count += 1
                else:
                    valid_count += 1

            preview_rows.append({
                "row_num": row_idx,
                "wb_nm_id": wb_nm_id,
                "seller_article": seller_article or None,
                "title": title or None,
                "promotion_name": promotion_name or None,
                "required_price": required_price,
                "current_wb_price": current_wb_price,
                "is_participating": is_participating,
                "product_id": product.id if product else None,
                "status": status,
                "message": message,
            })

        wb.close()

        total_rows = len(preview_rows)
        preview = AutoPromoImportPreview(
            import_id=0,
            user_id=user_id,
            marketplace_account_id=marketplace_account_id,
            total_rows=total_rows,
            valid_rows=valid_count,
            warning_rows=warning_count,
            error_rows=error_count,
            source=source,
            original_file_name=original_file_name,
            created_at=datetime.now(tz=UTC),
        )

        logger.info(
            "wb_auto_promo_conditions_import_preview_created",
            extra={
                "user_id": user_id,
                "total_rows": total_rows,
                "valid_rows": valid_count,
                "warning_rows": warning_count,
                "error_rows": error_count,
            },
        )

        return preview, preview_rows

    async def apply_import(
        self,
        preview_rows: list[dict[str, Any]],
        user_id: int,
        marketplace_account_id: int,
    ) -> int:
        """Apply the import: save conditions to the database."""
        now_utc = datetime.now(tz=UTC)
        saved_count = 0

        for row_data in preview_rows:
            if row_data["status"] == "error":
                continue

            wb_nm_id = row_data.get("wb_nm_id")
            required_price = row_data.get("required_price")
            if wb_nm_id is None or required_price is None:
                continue

            existing = await self.session.execute(
                select(WbAutoPromotionCondition).where(
                    WbAutoPromotionCondition.marketplace_account_id
                    == marketplace_account_id,
                    WbAutoPromotionCondition.wb_nm_id == wb_nm_id,
                    WbAutoPromotionCondition.source == "manual",
                    WbAutoPromotionCondition.promotion_name
                    == (row_data.get("promotion_name") or ""),
                )
            )
            condition = existing.scalar_one_or_none()

            if condition is None:
                condition = WbAutoPromotionCondition(
                    user_id=user_id,
                    marketplace_account_id=marketplace_account_id,
                    wb_nm_id=wb_nm_id,
                    source="manual",
                )
                self.session.add(condition)

            condition.seller_article = row_data.get("seller_article")
            condition.title = row_data.get("title")
            condition.promotion_name = row_data.get("promotion_name")
            condition.required_price = required_price
            condition.current_wb_price = row_data.get("current_wb_price")
            condition.is_participating = row_data.get("is_participating")
            condition.synced_at = now_utc
            saved_count += 1

        await self.session.flush()

        logger.info(
            "wb_auto_promo_conditions_import_applied",
            extra={
                "user_id": user_id,
                "marketplace_account_id": marketplace_account_id,
                "saved_count": saved_count,
            },
        )

        return saved_count

    async def _find_product_by_nm_id(
        self,
        marketplace_account_id: int,
        wb_nm_id: int,
        cache: dict[int, Product],
    ) -> Product | None:
        """Find a product by nmID, using cache."""
        if wb_nm_id in cache:
            return cache[wb_nm_id]

        result = await self.session.execute(
            select(Product).where(
                Product.marketplace_account_id == marketplace_account_id,
                Product.marketplace == "wb",
                (Product.external_product_id == str(wb_nm_id))
                | (Product.marketplace_article == str(wb_nm_id)),
            ).limit(1)
        )
        product = result.scalar_one_or_none()
        if product:
            cache[wb_nm_id] = product
        return product

    @staticmethod
    def _resolve_headers(raw_headers: tuple) -> dict[int, str]:
        """Map raw header strings to technical column names."""
        result: dict[int, str] = {}
        for idx, h in enumerate(raw_headers):
            h_str = str(h).strip().lower()
            if h_str in COLUMN_MAP_RU:
                result[idx] = COLUMN_MAP_RU[h_str]
            elif h_str in COLUMN_MAP_TECH:
                result[idx] = COLUMN_MAP_TECH[h_str]
            else:
                result[idx] = h_str
        return result

    @staticmethod
    def _parse_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_decimal(value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value).replace(",", "."))
        except (InvalidOperation, ValueError, TypeError):
            return None

    @staticmethod
    def _parse_bool(value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in ("да", "yes", "true", "1", "участвует"):
            return True
        if s in ("нет", "no", "false", "0", "не участвует"):
            return False
        return None
