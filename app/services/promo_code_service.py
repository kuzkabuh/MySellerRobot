"""version: 1.0.0
description: Promo code service for discount management.
updated: 2026-05-31
"""

import logging
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.domain import User
from app.models.enums import PromoType, PromoUsageStatus
from app.models.promo_codes import (
    PromoCode,
    PromoCodePeriod,
    PromoCodeTariff,
    PromoCodeUsage,
)
from app.models.subscriptions import SubscriptionTier

logger = logging.getLogger(__name__)

RESERVATION_TIMEOUT_MINUTES = 60


def normalize_code(code: str) -> str:
    return code.strip().upper()


class PromoValidationError(Exception):
    def __init__(self, message: str, reason: str = "unknown") -> None:
        super().__init__(message)
        self.reason = reason


class PromoCodeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_code(self, code: str) -> PromoCode | None:
        normalized = normalize_code(code)
        result = await self.session.execute(
            select(PromoCode)
            .options(
                selectinload(PromoCode.tariffs),
                selectinload(PromoCode.periods),
            )
            .where(PromoCode.code == normalized)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, promo_id: int) -> PromoCode | None:
        result = await self.session.execute(
            select(PromoCode)
            .options(
                selectinload(PromoCode.tariffs),
                selectinload(PromoCode.periods),
            )
            .where(PromoCode.id == promo_id)
        )
        return result.scalar_one_or_none()

    async def get_all(self) -> list[PromoCode]:
        result = await self.session.execute(
            select(PromoCode)
            .options(
                selectinload(PromoCode.tariffs),
                selectinload(PromoCode.periods),
            )
            .order_by(PromoCode.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        code: str,
        name: str,
        description: str | None = None,
        promo_type: str,
        discount_percent: int | None = None,
        discount_amount: Decimal | None = None,
        free_days: int | None = None,
        currency: str = "RUB",
        is_active: bool = True,
        starts_at: datetime | None = None,
        expires_at: datetime | None = None,
        max_uses_total: int | None = None,
        max_uses_per_user: int = 1,
        min_order_amount: Decimal | None = None,
        only_for_new_users: bool = False,
        created_by_admin_id: int | None = None,
        tariff_ids: list[int] | None = None,
        periods: list[str] | None = None,
    ) -> PromoCode:
        normalized = normalize_code(code)
        self._validate_code_format(normalized)
        self._validate_promo_params(
            promo_type=promo_type,
            discount_percent=discount_percent,
            discount_amount=discount_amount,
            free_days=free_days,
        )

        existing = await self.get_by_code(normalized)
        if existing:
            raise PromoValidationError(
                f"Промокод {normalized} уже существует", reason="code_exists"
            )

        promo = PromoCode(
            code=normalized,
            name=name,
            description=description,
            promo_type=promo_type,
            discount_percent=discount_percent,
            discount_amount=discount_amount,
            free_days=free_days,
            currency=currency,
            is_active=is_active,
            starts_at=starts_at,
            expires_at=expires_at,
            max_uses_total=max_uses_total,
            max_uses_per_user=max_uses_per_user,
            min_order_amount=min_order_amount,
            only_for_new_users=only_for_new_users,
            created_by_admin_id=created_by_admin_id,
        )
        self.session.add(promo)
        await self.session.flush()

        if tariff_ids:
            for tid in tariff_ids:
                self.session.add(
                    PromoCodeTariff(promo_code_id=promo.id, tariff_id=tid)
                )

        if periods:
            for p in periods:
                self.session.add(
                    PromoCodePeriod(promo_code_id=promo.id, period=p)
                )

        await self.session.flush()

        logger.info(
            "promo_code_created",
            extra={
                "promo_code_id": promo.id,
                "promo_code": promo.code,
                "promo_type": promo_type,
                "admin_user_id": created_by_admin_id,
            },
        )
        return promo

    async def update(
        self,
        promo_id: int,
        **kwargs: Any,
    ) -> PromoCode | None:
        promo = await self.get_by_id(promo_id)
        if not promo:
            return None

        tariff_ids = kwargs.pop("tariff_ids", None)
        periods = kwargs.pop("periods", None)

        if "code" in kwargs and kwargs["code"]:
            kwargs["code"] = normalize_code(kwargs["code"])
            self._validate_code_format(kwargs["code"])
            if kwargs["code"] != promo.code:
                existing = await self.get_by_code(kwargs["code"])
                if existing and existing.id != promo_id:
                    raise PromoValidationError(
                        f"Промокод {kwargs['code']} уже существует",
                        reason="code_exists",
                    )

        if "promo_type" in kwargs:
            self._validate_promo_params(
                promo_type=kwargs.get("promo_type", promo.promo_type),
                discount_percent=kwargs.get(
                    "discount_percent", promo.discount_percent
                ),
                discount_amount=kwargs.get(
                    "discount_amount", promo.discount_amount
                ),
                free_days=kwargs.get("free_days", promo.free_days),
            )

        for key, value in kwargs.items():
            if hasattr(promo, key):
                setattr(promo, key, value)

        if tariff_ids is not None:
            for pt in promo.tariffs:
                await self.session.delete(pt)
            for tid in tariff_ids:
                self.session.add(
                    PromoCodeTariff(promo_code_id=promo.id, tariff_id=tid)
                )

        if periods is not None:
            for pp in promo.periods:
                await self.session.delete(pp)
            for p in periods:
                self.session.add(
                    PromoCodePeriod(promo_code_id=promo.id, period=p)
                )

        await self.session.flush()

        logger.info(
            "promo_code_updated",
            extra={
                "promo_code_id": promo.id,
                "promo_code": promo.code,
                "changed_fields": list(kwargs.keys()),
            },
        )
        return promo

    async def toggle(self, promo_id: int) -> PromoCode | None:
        promo = await self.get_by_id(promo_id)
        if not promo:
            return None
        promo.is_active = not promo.is_active
        await self.session.flush()
        logger.info(
            "promo_code_toggled",
            extra={
                "promo_code_id": promo.id,
                "promo_code": promo.code,
                "is_active": promo.is_active,
            },
        )
        return promo

    async def validate(
        self,
        *,
        user: User,
        tariff: SubscriptionTier,
        period: str,
        code: str,
    ) -> PromoCode:
        promo = await self.get_by_code(code)
        if not promo:
            raise PromoValidationError("Промокод не найден", reason="not_found")

        if not promo.is_active:
            raise PromoValidationError(
                "Промокод отключён", reason="inactive"
            )

        now = datetime.now(tz=UTC)
        if promo.starts_at and promo.starts_at > now:
            raise PromoValidationError(
                "Промокод ещё не начал действовать", reason="not_started"
            )
        if promo.expires_at and promo.expires_at < now:
            raise PromoValidationError(
                "Промокод истёк", reason="expired"
            )

        if promo.max_uses_total is not None and promo.used_count >= promo.max_uses_total:
            raise PromoValidationError(
                "Лимит использований промокода исчерпан", reason="max_total"
            )

        user_usage = await self._count_user_applied_uses(user.id, promo.id)
        if user_usage >= promo.max_uses_per_user:
            raise PromoValidationError(
                "Вы уже использовали этот промокод", reason="max_per_user"
            )

        user_reserved = await self._count_user_active_reservations(
            user.id, promo.id
        )
        if user_reserved > 0:
            raise PromoValidationError(
                "Промокод уже зарезервирован для вас. Завершите оплату или подождите.",
                reason="already_reserved",
            )

        if promo.tariffs:
            allowed_ids = {pt.tariff_id for pt in promo.tariffs}
            if tariff.id not in allowed_ids:
                raise PromoValidationError(
                    "Промокод не подходит для этого тарифа",
                    reason="tariff_not_allowed",
                )

        if promo.periods:
            allowed_periods = {pp.period for pp in promo.periods}
            if period not in allowed_periods:
                raise PromoValidationError(
                    "Промокод не подходит для этого периода",
                    reason="period_not_allowed",
                )

        if promo.only_for_new_users:
            has_payments = await self._user_has_payments(user.id)
            if has_payments:
                raise PromoValidationError(
                    "Промокод доступен только новым пользователям",
                    reason="not_new_user",
                )

        return promo

    async def calculate_discount(
        self,
        *,
        tariff_price: Decimal,
        promo: PromoCode,
    ) -> tuple[Decimal, int | None]:
        if promo.promo_type == PromoType.PERCENT_DISCOUNT:
            pct = promo.discount_percent or 0
            discount = (tariff_price * Decimal(pct) / Decimal(100)).quantize(
                Decimal("0.01")
            )
            return discount, None

        if promo.promo_type == PromoType.FIXED_DISCOUNT:
            discount = promo.discount_amount or Decimal("0")
            return discount, None

        if promo.promo_type == PromoType.FREE_DAYS:
            return tariff_price, promo.free_days

        return Decimal("0"), None

    async def reserve_usage(
        self,
        *,
        user: User,
        promo: PromoCode,
        tariff: SubscriptionTier,
        period: str,
        original_amount: Decimal,
        discount_amount: Decimal,
        final_amount: Decimal,
        free_days_applied: int | None = None,
    ) -> PromoCodeUsage:
        usage = PromoCodeUsage(
            promo_code_id=promo.id,
            user_id=user.id,
            tariff_id=tariff.id,
            period=period,
            original_amount=original_amount,
            discount_amount=discount_amount,
            final_amount=final_amount,
            free_days_applied=free_days_applied,
            used_at=datetime.now(tz=UTC),
            status=PromoUsageStatus.RESERVED,
        )
        self.session.add(usage)
        await self.session.flush()

        logger.info(
            "promo_code_reserved",
            extra={
                "promo_code_id": promo.id,
                "promo_code": promo.code,
                "user_id": user.id,
                "tariff_id": tariff.id,
                "period": period,
                "original_amount": str(original_amount),
                "discount_amount": str(discount_amount),
                "final_amount": str(final_amount),
            },
        )
        return usage

    async def confirm_usage(
        self,
        *,
        usage_id: int,
        payment_id: int | None = None,
        subscription_id: int | None = None,
        provider_payment_id: str | None = None,
    ) -> PromoCodeUsage | None:
        usage = await self.session.get(PromoCodeUsage, usage_id)
        if not usage:
            return None

        usage.status = PromoUsageStatus.APPLIED
        usage.payment_id = payment_id
        usage.subscription_id = subscription_id
        usage.provider_payment_id = provider_payment_id

        promo = await self.session.get(PromoCode, usage.promo_code_id)
        if promo:
            promo.used_count = (promo.used_count or 0) + 1

        await self.session.flush()

        logger.info(
            "promo_code_applied",
            extra={
                "promo_code_id": usage.promo_code_id,
                "usage_id": usage.id,
                "user_id": usage.user_id,
                "payment_id": payment_id,
            },
        )
        return usage

    async def cancel_usage(self, usage_id: int) -> PromoCodeUsage | None:
        usage = await self.session.get(PromoCodeUsage, usage_id)
        if not usage:
            return None

        if usage.status == PromoUsageStatus.APPLIED:
            return usage

        usage.status = PromoUsageStatus.CANCELLED
        await self.session.flush()

        logger.info(
            "promo_code_cancelled",
            extra={
                "promo_code_id": usage.promo_code_id,
                "usage_id": usage.id,
                "user_id": usage.user_id,
            },
        )
        return usage

    async def cancel_usage_by_payment(
        self, provider_payment_id: str
    ) -> None:
        result = await self.session.execute(
            select(PromoCodeUsage).where(
                PromoCodeUsage.provider_payment_id == provider_payment_id,
                PromoCodeUsage.status == PromoUsageStatus.RESERVED,
            )
        )
        usage = result.scalar_one_or_none()
        if usage:
            await self.cancel_usage(usage.id)

    async def get_active_reservation(
        self, user_id: int, promo_id: int
    ) -> PromoCodeUsage | None:
        cutoff = datetime.now(tz=UTC) - timedelta(
            minutes=RESERVATION_TIMEOUT_MINUTES
        )
        result = await self.session.execute(
            select(PromoCodeUsage).where(
                PromoCodeUsage.user_id == user_id,
                PromoCodeUsage.promo_code_id == promo_id,
                PromoCodeUsage.status == PromoUsageStatus.RESERVED,
                PromoCodeUsage.used_at > cutoff,
            )
        )
        return result.scalar_one_or_none()

    async def get_usages(
        self, promo_id: int, limit: int = 100
    ) -> list[PromoCodeUsage]:
        result = await self.session.execute(
            select(PromoCodeUsage)
            .where(PromoCodeUsage.promo_code_id == promo_id)
            .order_by(PromoCodeUsage.used_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_usage_stats(self, promo_id: int) -> dict[str, Any]:
        result = await self.session.execute(
            select(
                func.count(PromoCodeUsage.id).label("total"),
                func.sum(PromoCodeUsage.discount_amount).label(
                    "total_discount"
                ),
            ).where(
                PromoCodeUsage.promo_code_id == promo_id,
                PromoCodeUsage.status == PromoUsageStatus.APPLIED,
            )
        )
        row = result.one()
        return {
            "total_uses": row.total or 0,
            "total_discount": row.total_discount or Decimal("0"),
        }

    async def cleanup_expired_reservations(self) -> int:
        cutoff = datetime.now(tz=UTC) - timedelta(
            minutes=RESERVATION_TIMEOUT_MINUTES
        )
        result = await self.session.execute(
            select(PromoCodeUsage).where(
                PromoCodeUsage.status == PromoUsageStatus.RESERVED,
                PromoCodeUsage.used_at < cutoff,
            )
        )
        expired = list(result.scalars().all())
        for usage in expired:
            usage.status = PromoUsageStatus.CANCELLED
        if expired:
            await self.session.flush()
            logger.info(
                "promo_reservations_cleaned_up",
                extra={"count": len(expired)},
            )
        return len(expired)

    async def _count_user_applied_uses(
        self, user_id: int, promo_id: int
    ) -> int:
        result = await self.session.execute(
            select(func.count(PromoCodeUsage.id)).where(
                PromoCodeUsage.user_id == user_id,
                PromoCodeUsage.promo_code_id == promo_id,
                PromoCodeUsage.status == PromoUsageStatus.APPLIED,
            )
        )
        return int(result.scalar_one() or 0)

    async def _count_user_active_reservations(
        self, user_id: int, promo_id: int
    ) -> int:
        cutoff = datetime.now(tz=UTC) - timedelta(
            minutes=RESERVATION_TIMEOUT_MINUTES
        )
        result = await self.session.execute(
            select(func.count(PromoCodeUsage.id)).where(
                PromoCodeUsage.user_id == user_id,
                PromoCodeUsage.promo_code_id == promo_id,
                PromoCodeUsage.status == PromoUsageStatus.RESERVED,
                PromoCodeUsage.used_at > cutoff,
            )
        )
        return int(result.scalar_one() or 0)

    async def _user_has_payments(self, user_id: int) -> bool:
        from app.models.enums import PaymentStatus
        from app.models.subscriptions import Payment

        result = await self.session.execute(
            select(func.count(Payment.id)).where(
                Payment.user_id == user_id,
                Payment.status == PaymentStatus.SUCCEEDED,
            )
        )
        return int(result.scalar_one() or 0) > 0

    @staticmethod
    def _validate_code_format(code: str) -> None:
        if not code:
            raise PromoValidationError("Код промокода не может быть пустым", reason="empty_code")
        if len(code) > 64:
            raise PromoValidationError(
                "Код промокода слишком длинный (макс. 64 символа)",
                reason="code_too_long",
            )
        if not re.match(r"^[A-Z0-9_-]+$", code):
            raise PromoValidationError(
                "Код может содержать только латинские буквы, цифры, дефис и подчёркивание",
                reason="invalid_chars",
            )

    @staticmethod
    def _validate_promo_params(
        *,
        promo_type: str,
        discount_percent: int | None,
        discount_amount: Decimal | None,
        free_days: int | None,
    ) -> None:
        if promo_type == PromoType.PERCENT_DISCOUNT:
            if discount_percent is None or discount_percent < 1 or discount_percent > 100:
                raise PromoValidationError(
                    "Процент скидки должен быть от 1 до 100",
                    reason="invalid_percent",
                )
        elif promo_type == PromoType.FIXED_DISCOUNT:
            if discount_amount is None or discount_amount < Decimal("1"):
                raise PromoValidationError(
                    "Фиксированная скидка должна быть не менее 1 рубля",
                    reason="invalid_amount",
                )
        elif promo_type == PromoType.FREE_DAYS:
            if free_days is None or free_days < 1:
                raise PromoValidationError(
                    "Количество бесплатных дней должно быть не менее 1",
                    reason="invalid_free_days",
                )
        else:
            raise PromoValidationError(
                f"Неизвестный тип промокода: {promo_type}",
                reason="unknown_type",
            )
