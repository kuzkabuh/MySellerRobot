"""version: 1.0.0
description: Tests for MarketplaceAccountRepository.list_active_accounts and
             commission sync handler error handling.
updated: 2026-05-20
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.enums import AccountStatus, Marketplace
from app.repositories.accounts import MarketplaceAccountRepository


class FakeAccount:
    """Minimal fake MarketplaceAccount for unit tests."""

    def __init__(
        self,
        *,
        id: int,
        marketplace: Marketplace,
        is_active: bool,
        status: AccountStatus,
        created_at: datetime,
    ) -> None:
        self.id = id
        self.marketplace = marketplace
        self.is_active = is_active
        self.status = status
        self.created_at = created_at


class TestListActiveAccounts:
    @pytest.fixture
    def session(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def repo(self, session: AsyncMock) -> MarketplaceAccountRepository:
        return MarketplaceAccountRepository(session)

    def _make_scalars_result(self, accounts: list[FakeAccount]) -> MagicMock:
        result = MagicMock()
        result.scalars.return_value.all.return_value = accounts
        return result

    @pytest.mark.asyncio
    async def test_returns_only_active_accounts(
        self, repo: MarketplaceAccountRepository, session: AsyncMock
    ) -> None:
        active = FakeAccount(
            id=1,
            marketplace=Marketplace.WB,
            is_active=True,
            status=AccountStatus.ACTIVE,
            created_at=datetime.now(UTC),
        )
        session.execute = AsyncMock(return_value=self._make_scalars_result([active]))

        result = await repo.list_active_accounts()
        assert len(result) == 1
        assert result[0].id == 1

    @pytest.mark.asyncio
    async def test_does_not_return_disabled_accounts(
        self, repo: MarketplaceAccountRepository, session: AsyncMock
    ) -> None:
        session.execute = AsyncMock(return_value=self._make_scalars_result([]))

        result = await repo.list_active_accounts()
        assert result == []

    @pytest.mark.asyncio
    async def test_filters_by_marketplace_wb(
        self, repo: MarketplaceAccountRepository, session: AsyncMock
    ) -> None:
        wb_account = FakeAccount(
            id=1,
            marketplace=Marketplace.WB,
            is_active=True,
            status=AccountStatus.ACTIVE,
            created_at=datetime.now(UTC),
        )
        session.execute = AsyncMock(return_value=self._make_scalars_result([wb_account]))

        result = await repo.list_active_accounts(marketplace=Marketplace.WB)
        assert len(result) == 1
        assert result[0].marketplace == Marketplace.WB

    @pytest.mark.asyncio
    async def test_filters_by_marketplace_ozon(
        self, repo: MarketplaceAccountRepository, session: AsyncMock
    ) -> None:
        ozon_account = FakeAccount(
            id=2,
            marketplace=Marketplace.OZON,
            is_active=True,
            status=AccountStatus.ACTIVE,
            created_at=datetime.now(UTC),
        )
        session.execute = AsyncMock(return_value=self._make_scalars_result([ozon_account]))

        result = await repo.list_active_accounts(marketplace=Marketplace.OZON)
        assert len(result) == 1
        assert result[0].marketplace == Marketplace.OZON


class TestSyncWbCommissionsHandler:
    """Tests for sync_wb_commissions_handler error handling."""

    @pytest.fixture
    def mock_callback(self) -> MagicMock:
        cb = MagicMock()
        cb.from_user.id = 12345
        cb.message = MagicMock()
        cb.message.edit_text = AsyncMock()
        cb.answer = AsyncMock()
        return cb

    @pytest.mark.asyncio
    async def test_no_active_accounts_shows_message(self, mock_callback: MagicMock) -> None:
        from app.bot.handlers.commissions import sync_wb_commissions_handler

        with (
            patch(
                "app.bot.handlers.commissions._is_admin_telegram",
                return_value=True,
            ),
            patch(
                "app.bot.handlers.commissions.AsyncSessionFactory",
            ) as mock_factory,
        ):
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_repo = MagicMock()
            mock_repo.list_active_accounts = AsyncMock(return_value=[])

            with patch(
                "app.bot.handlers.commissions.MarketplaceAccountRepository",
                return_value=mock_repo,
            ):
                await sync_wb_commissions_handler(mock_callback)

            mock_callback.message.edit_text.assert_any_call(
                "Нет активных WB-кабинетов для синхронизации."
            )

    @pytest.mark.asyncio
    async def test_internal_error_shows_friendly_message(self, mock_callback: MagicMock) -> None:
        from app.bot.handlers.commissions import sync_wb_commissions_handler

        with (
            patch(
                "app.bot.handlers.commissions._is_admin_telegram",
                return_value=True,
            ),
            patch(
                "app.bot.handlers.commissions.AsyncSessionFactory",
            ) as mock_factory,
        ):
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_repo = MagicMock()
            mock_repo.list_active_accounts = AsyncMock(side_effect=Exception("DB connection lost"))

            with patch(
                "app.bot.handlers.commissions.MarketplaceAccountRepository",
                return_value=mock_repo,
            ):
                await sync_wb_commissions_handler(mock_callback)

            calls = [c[0][0] for c in mock_callback.message.edit_text.call_args_list]
            assert any("⚠️" in call for call in calls)
            assert any("Ошибка зафиксирована в логах" in call for call in calls)
