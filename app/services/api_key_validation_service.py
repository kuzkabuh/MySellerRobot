"""version: 1.0.0
description: API key validation service for WB and Ozon marketplaces.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenCipher, mask_secret
from app.integrations.ozon import OzonClient
from app.integrations.wb import WildberriesClient
from app.models.domain import ApiKeyAuditLog, MarketplaceAccount
from app.models.enums import Marketplace

logger = logging.getLogger(__name__)


@dataclass
class ApiKeyCheckResult:
    success: bool
    status: str
    message: str
    permissions: list[str] = field(default_factory=list)
    missing_permissions: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


class ApiKeyValidationError(Exception):
    pass


class ApiKeyValidationService:
    WB_REQUIRED_PERMISSIONS = ["orders", "content", "analytics", "finance"]
    OZON_REQUIRED_PERMISSIONS = ["posting", "product", "finance"]

    def __init__(self, session: AsyncSession, cipher: TokenCipher) -> None:
        self.session = session
        self.cipher = cipher

    async def validate_wb_key(self, api_key: str) -> ApiKeyCheckResult:
        if not api_key or len(api_key) < 10:
            return ApiKeyCheckResult(
                success=False,
                status="auth_error",
                message="API-ключ слишком короткий или пустой",
            )

        try:
            client = WildberriesClient(api_key=api_key)
            await client.check_connection()
            permissions = []
            missing = []

            try:
                await client.get_new_fbs_orders()
                permissions.append("orders")
            except Exception:
                missing.append("orders")

            try:
                await client.get_cards_list(cursor={"limit": 1})
                permissions.append("content")
            except Exception:
                missing.append("content")

            return ApiKeyCheckResult(
                success=len(missing) == 0,
                status="active" if len(missing) == 0 else "insufficient_permissions",
                message="Подключение успешно" if len(missing) == 0
                else f"Недостаточно прав: {', '.join(missing)}",
                permissions=permissions,
                missing_permissions=missing,
            )
        except Exception as exc:
            error_msg = str(exc)
            if "401" in error_msg or "Unauthorized" in error_msg.lower():
                return ApiKeyCheckResult(
                    success=False,
                    status="auth_error",
                    message="Неверный API-ключ Wildberries",
                )
            if "403" in error_msg or "Forbidden" in error_msg.lower():
                return ApiKeyCheckResult(
                    success=False,
                    status="insufficient_permissions",
                    message="Недостаточно прав доступа",
                )
            return ApiKeyCheckResult(
                success=False,
                status="auth_error",
                message=f"Ошибка подключения: {error_msg[:200]}",
            )

    async def validate_ozon_key(
        self, api_key: str, client_id: str
    ) -> ApiKeyCheckResult:
        if not api_key or not client_id:
            return ApiKeyCheckResult(
                success=False,
                status="auth_error",
                message="API-Key и Client-Id обязательны",
            )

        try:
            client = OzonClient(api_key=api_key, client_id=client_id)
            await client.check_connection()
            permissions = []
            missing = []

            try:
                await client.get_product_list(limit=1)
                permissions.append("product")
            except Exception:
                missing.append("product")

            try:
                now = datetime.now(UTC)
                await client.get_fbs_postings(now, now, limit=1)
                permissions.append("posting")
            except Exception:
                missing.append("posting")

            return ApiKeyCheckResult(
                success=len(missing) == 0,
                status="active" if len(missing) == 0 else "insufficient_permissions",
                message="Подключение успешно" if len(missing) == 0
                else f"Недостаточно прав: {', '.join(missing)}",
                permissions=permissions,
                missing_permissions=missing,
            )
        except Exception as exc:
            error_msg = str(exc)
            if "401" in error_msg or "Unauthorized" in error_msg.lower():
                return ApiKeyCheckResult(
                    success=False,
                    status="auth_error",
                    message="Неверный API-Key или Client-Id Ozon",
                )
            if "403" in error_msg or "Forbidden" in error_msg.lower():
                return ApiKeyCheckResult(
                    success=False,
                    status="insufficient_permissions",
                    message="Недостаточно прав доступа",
                )
            return ApiKeyCheckResult(
                success=False,
                status="auth_error",
                message=f"Ошибка подключения: {error_msg[:200]}",
            )

    async def check_account(self, account: MarketplaceAccount) -> ApiKeyCheckResult:
        api_key = self.cipher.decrypt(account.encrypted_api_key)

        if account.marketplace == Marketplace.WB:
            result = await self.validate_wb_key(api_key)
        elif account.marketplace == Marketplace.OZON:
            client_id = ""
            if account.encrypted_client_id:
                client_id = self.cipher.decrypt(account.encrypted_client_id)
            result = await self.validate_ozon_key(api_key, client_id)
        else:
            result = ApiKeyCheckResult(
                success=False,
                status="auth_error",
                message="Неизвестный маркетплейс",
            )

        account.api_key_status = result.status
        account.api_key_checked_at = datetime.now(UTC)
        account.api_key_check_result = {
            "permissions": result.permissions,
            "missing_permissions": result.missing_permissions,
            "message": result.message,
        }

        if result.success:
            from app.models.enums import AccountStatus
            account.status = AccountStatus.ACTIVE

        await self.session.commit()
        return result

    async def log_key_action(
        self,
        user_id: int,
        account_id: int,
        marketplace: str,
        action: str,
        old_key: str | None = None,
        new_key: str | None = None,
        check_result: str | None = None,
        check_details: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> None:
        entry = ApiKeyAuditLog(
            user_id=user_id,
            account_id=account_id,
            marketplace=marketplace,
            action=action,
            old_key_mask=mask_secret(old_key) if old_key else None,
            new_key_mask=mask_secret(new_key) if new_key else None,
            check_result=check_result,
            check_details=check_details,
            ip_address=ip_address[:64] if ip_address else None,
        )
        self.session.add(entry)
        await self.session.commit()
