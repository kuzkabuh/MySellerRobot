"""version: 1.0.0
description: Product cost management and Excel import application service.
updated: 2026-05-14
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Marketplace
from app.repositories.products import ProductCostRepository, ProductRepository
from app.schemas.products import CostUpdate
from app.services.unit_economics.excel_cost_import import ExcelCostImportService


class CostManagementError(RuntimeError):
    """Raised when a cost update cannot be applied safely."""


@dataclass(slots=True)
class CostImportResult:
    updated: int
    errors: list[str]


class CostManagementService:
    """Apply manual and Excel cost updates with cost history preservation."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.products = ProductRepository(session)
        self.costs = ProductCostRepository(session)
        self.excel = ExcelCostImportService()

    async def update_by_article(
        self,
        *,
        user_id: int,
        article: str,
        cost_price: Decimal,
        package_cost: Decimal,
        additional_cost: Decimal,
        tax_rate: Decimal,
        valid_from: datetime,
        marketplace: Marketplace | None = None,
        account_name: str | None = None,
        comment: str | None = None,
    ) -> None:
        matches = await self.products.find_for_user_by_article(
            user_id=user_id,
            article=article,
            account_name=account_name,
            marketplace=marketplace,
        )
        if not matches:
            raise CostManagementError(
                "Товар с таким артикулом не найден. Сначала синхронизируйте товары."
            )
        if len(matches) > 1:
            raise CostManagementError(
                "Найдено несколько товаров с таким артикулом. "
                "Укажите кабинет или используйте Excel."
            )
        await self.costs.add_cost(
            CostUpdate(
                product_id=matches[0].id,
                cost_price=cost_price,
                package_cost=package_cost,
                additional_cost=additional_cost,
                tax_rate=tax_rate,
                valid_from=valid_from,
                comment=comment,
            )
        )
        await self.session.commit()

    async def import_excel(self, *, user_id: int, path: Path) -> CostImportResult:
        rows, parse_errors = self.excel.parse(path)
        errors = list(parse_errors)
        updated = 0
        for number, row in enumerate(rows, start=2):
            try:
                marketplace = Marketplace(row.marketplace.upper())
                matches = await self.products.find_for_user_by_article(
                    user_id=user_id,
                    article=row.seller_article or row.marketplace_article,
                    account_name=row.account,
                    marketplace=marketplace,
                )
                if not matches:
                    errors.append(f"Строка {number}: товар не найден")
                    continue
                if len(matches) > 1:
                    errors.append(f"Строка {number}: найдено несколько товаров")
                    continue
                await self.costs.add_cost(
                    CostUpdate(
                        product_id=matches[0].id,
                        cost_price=row.cost_price,
                        package_cost=row.package_cost,
                        additional_cost=row.additional_cost,
                        tax_rate=row.tax_rate,
                        valid_from=(
                            row.valid_from.replace(tzinfo=UTC)
                            if row.valid_from.tzinfo is None
                            else row.valid_from
                        ),
                        comment="Excel-импорт",
                    )
                )
                updated += 1
            except (ValueError, InvalidOperation) as exc:
                errors.append(f"Строка {number}: {exc}")
        if updated:
            await self.session.commit()
        else:
            await self.session.rollback()
        return CostImportResult(updated=updated, errors=errors)


def parse_manual_cost_line(value: str) -> tuple[str, Decimal, Decimal, Decimal, Decimal, datetime]:
    """Parse Telegram cost input line.

    Format: article; cost; package; additional; tax_percent; valid_from
    """

    parts = [part.strip() for part in value.split(";")]
    if len(parts) != 6:
        raise CostManagementError(
            "Нужен формат: Артикул; Себестоимость; Упаковка; Доп. расходы; Налог %; Дата"
        )
    article = parts[0]
    if not article:
        raise CostManagementError("Артикул не должен быть пустым.")
    try:
        return (
            article,
            Decimal(parts[1]).quantize(Decimal("0.01")),
            Decimal(parts[2]).quantize(Decimal("0.01")),
            Decimal(parts[3]).quantize(Decimal("0.01")),
            (Decimal(parts[4]) / Decimal("100")).quantize(Decimal("0.0001")),
            datetime.fromisoformat(parts[5]).replace(tzinfo=UTC),
        )
    except (InvalidOperation, ValueError) as exc:
        raise CostManagementError(
            "Не удалось разобрать строку. Проверьте числа и дату в формате YYYY-MM-DD."
        ) from exc
