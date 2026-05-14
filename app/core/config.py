"""version: 1.0.0
description: Pydantic settings for application configuration.
updated: 2026-05-14
"""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    app_debug: bool = False
    app_secret_key: SecretStr = Field(default=SecretStr("change-me"))
    encryption_key: SecretStr = Field(default=SecretStr("PASTE_FERNET_KEY_HERE"))

    bot_token: SecretStr = Field(default=SecretStr(""))
    admin_telegram_ids: str = ""

    database_url: str = (
        "postgresql+asyncpg://seller_bot:seller_bot@localhost:5432/seller_profit_bot"
    )
    redis_url: str = "redis://localhost:6379/0"

    wb_base_marketplace_url: str = "https://marketplace-api.wildberries.ru"
    wb_base_common_url: str = "https://common-api.wildberries.ru"
    wb_base_content_url: str = "https://content-api.wildberries.ru"
    wb_base_analytics_url: str = "https://seller-analytics-api.wildberries.ru"
    wb_base_finance_url: str = "https://finance-api.wildberries.ru"

    ozon_base_url: str = "https://api-seller.ozon.ru"

    order_poll_interval_seconds: int = 180
    daily_report_hour: int = 9
    default_tax_rate: float = 0.06
    default_package_cost: float = 0
    log_level: str = "INFO"

    @property
    def admin_ids(self) -> set[int]:
        return {
            int(item.strip())
            for item in self.admin_telegram_ids.split(",")
            if item.strip().isdigit()
        }


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""

    return Settings()
