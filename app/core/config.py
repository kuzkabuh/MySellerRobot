"""version: 1.2.0
description: Pydantic settings for application configuration.
updated: 2026-05-15
"""

from functools import lru_cache
from typing import Any

from pydantic import Field, SecretStr, model_validator
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
    wb_base_statistics_url: str = "https://statistics-api.wildberries.ru"

    ozon_base_url: str = "https://api-seller.ozon.ru"

    order_poll_interval_seconds: int = 180
    daily_report_hour: int = 9
    backfill_default_days: int = 30
    backfill_chunk_days: int = 7
    web_base_url: str = "http://localhost:8000"
    web_app_base_url: str | None = None
    web_login_token_ttl_minutes: int = 10
    web_session_ttl_hours: int = 168
    default_tax_rate: float = 0.06
    default_package_cost: float = 0
    deploy_project_dir: str = "/opt/mpcontrol"
    deploy_log_dir: str = "/opt/mpcontrol/logs/deploy"
    deploy_runtime_dir: str = "/opt/mpcontrol/runtime"
    backup_dir: str = "/opt/mpcontrol/backups"
    backup_retention_days: int = 30
    enable_telegram_deploy_notifications: bool = True
    enable_telegram_deploy_commands: bool = False
    telegram_deploy_mode: str = "trigger"
    deploy_update_command: str = "bash deploy/update.sh --non-interactive"
    deploy_update_trigger_file: str = "/opt/mpcontrol/runtime/telegram_update_request.json"
    deploy_metadata_file: str = "/opt/mpcontrol/runtime/deploy_metadata.json"
    log_level: str = "INFO"

    @model_validator(mode="before")
    @classmethod
    def normalize_web_base_url_alias(cls, values: Any) -> Any:
        if (
            isinstance(values, dict)
            and values.get("web_app_base_url")
            and not values.get("web_base_url")
        ):
            values["web_base_url"] = values["web_app_base_url"]
        return values

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
