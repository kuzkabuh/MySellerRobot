"""version: 1.0.0
description: Product synchronization service for Wildberries and Ozon accounts.
updated: 2026-05-14
"""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenCipher
from app.integrations.ozon import OzonClient
from app.integrations.wb import WildberriesClient
from app.models.domain import MarketplaceAccount
from app.models.enums import Marketplace
from app.repositories.products import ProductRepository


class ProductSyncService:
    """Synchronize product cards from marketplace APIs into local catalog."""

    def __init__(
        self,
        session: AsyncSession,
        cipher: TokenCipher | None = None,
    ) -> None:
        self.session = session
        self.repo = ProductRepository(session)
        self.cipher = cipher or TokenCipher()

    async def sync_account_products(self, account: MarketplaceAccount) -> int:
        if account.marketplace == Marketplace.WB:
            count = await self._sync_wb(account)
        else:
            count = await self._sync_ozon(account)
        account.last_success_sync_at = datetime.now(tz=UTC)
        await self.session.commit()
        return count

    async def _sync_wb(self, account: MarketplaceAccount) -> int:
        client = WildberriesClient(self.cipher.decrypt(account.encrypted_api_key))
        cursor: dict[str, object] = {"limit": 100}
        count = 0
        while True:
            data = await client.get_cards_list(cursor)
            cards = data.get("cards", [])
            if not isinstance(cards, list) or not cards:
                break
            for card in cards:
                if not isinstance(card, dict):
                    continue
                product = client.normalize_card_product(
                    payload=card,
                    user_id=account.user_id,
                    account_id=account.id,
                )
                if product.external_product_id:
                    await self.repo.upsert(product)
                    count += 1
            response_cursor = data.get("cursor")
            if not isinstance(response_cursor, dict):
                break
            total = int(response_cursor.get("total", 0) or 0)
            if total < 100:
                break
            cursor = {
                "limit": 100,
                "updatedAt": response_cursor.get("updatedAt"),
                "nmID": response_cursor.get("nmID"),
            }
        return count

    async def _sync_ozon(self, account: MarketplaceAccount) -> int:
        api_key = self.cipher.decrypt(account.encrypted_api_key)
        client_id = self.cipher.decrypt(account.encrypted_client_id or "")
        client = OzonClient(client_id, api_key)
        last_id = ""
        count = 0
        while True:
            data = await client.get_product_list(last_id=last_id, limit=100)
            result = data.get("result", {})
            if not isinstance(result, dict):
                break
            items = result.get("items", [])
            if not isinstance(items, list) or not items:
                break
            for item in items:
                if not isinstance(item, dict):
                    continue
                product = client.normalize_product(
                    payload=item,
                    user_id=account.user_id,
                    account_id=account.id,
                )
                if product.external_product_id:
                    await self.repo.upsert(product)
                    count += 1
            last_id = str(result.get("last_id") or "")
            if not last_id:
                break
        return count
