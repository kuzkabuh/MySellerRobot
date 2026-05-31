"""version: 2.0.0
description: Pydantic settings for application configuration.
updated: 2026-05-21
"""

import logging
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_LOCALHOST_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0"}


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
    ozon_commissions_source_url: str = (
        "https://seller-edu.ozon.ru/libra/commissions-tariffs/"
        "commissions-tariffs-ozon/komissii-tovary-uslugi"
    )
    ozon_commissions_fetch_mode: str = "auto"
    ozon_commissions_browser_fallback_enabled: bool = True
    ozon_commissions_browser_headless: bool = True
    ozon_commissions_browser_timeout_seconds: int = 60
    ozon_commissions_download_dir: str = "/app/runtime/ozon_commissions"
    ozon_commissions_cookie_enabled: bool = False
    ozon_commissions_cookie_file: str = "/app/runtime/secret/ozon_seller_edu_cookies.json"

    # YooKassa payment settings
    yookassa_shop_id: str = ""
    yookassa_secret_key: SecretStr = Field(default=SecretStr(""))
    yookassa_return_url: str | None = None
    yookassa_webhook_url: str | None = None

    # Support contact
    support_telegram_username: str = "mpcontrol_support"

    daily_report_hour: int = 9
    backfill_default_days: int = 30
    backfill_chunk_days: int = 7
    wb_report_detailed_limit: int = 1000
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
    # Wildberries MRC (recommended retail price) pricing
    wb_mrc_promo_max_discount_percent: int = 10
    wb_price_before_discount_multiplier: int = 4

    # Wildberries promotions sync
    wb_promotions_sync_enabled: bool = True
    wb_promotions_sync_time: str = "00:15"
    wb_promotions_sync_timezone: str = "Europe/Moscow"
    wb_promotions_history_retention_days: int = 90
    wb_promotions_page_limit: int = 1000
    wb_base_calendar_url: str = "https://dp-calendar-api.wildberries.ru"
    wb_base_discounts_prices_url: str = "https://discounts-prices-api.wildberries.ru"

    # MRC import settings
    mrc_import_max_file_size_mb: int = 10
    mrc_import_max_rows: int = 5000
    mrc_import_allow_clear: bool = True

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

    @property
    def is_production(self) -> bool:
        return self.app_env in ("production", "prod", "staging")

    def is_safe_web_url(self, url: str) -> bool:
        """Check if a URL is safe for production use.

        In production, requires HTTPS and a non-localhost hostname.
        In development, allows HTTP and localhost.
        """
        if not url:
            return False
        try:
            parsed = urlparse(url)
        except Exception:
            return False

        if parsed.scheme not in ("https", "http"):
            return False

        is_localhost = parsed.hostname in _LOCALHOST_HOSTS if parsed.hostname else True

        if self.is_production:
            if parsed.scheme != "https":
                logger.warning(
                    "production_url_not_https",
                    extra={"url": url, "scheme": parsed.scheme},
                )
                return False
            if is_localhost:
                logger.warning(
                    "production_url_localhost",
                    extra={"url": url, "hostname": parsed.hostname},
                )
                return False
            return True

        return True

    def get_web_base_url(self) -> str:
        """Return web_base_url with production safety check."""
        url = self.web_base_url.rstrip("/")
        if self.is_production and not self.is_safe_web_url(url):
            raise ValueError(
                f"WEB_BASE_URL '{url}' is not safe for production. "
                f"Must be a public HTTPS URL (not localhost or HTTP)."
            )
        return url

    def get_yookassa_return_url(self) -> str:
        """Return YooKassa return URL with validation."""
        if self.yookassa_return_url:
            url = self.yookassa_return_url
        else:
            web_url = self.get_web_base_url()
            if web_url.endswith("/web"):
                web_url = web_url[:-4]
            url = f"{web_url}/payment/success"

        if self.is_production and not self.is_safe_web_url(url):
            raise ValueError(
                f"YooKassa return_url '{url}' is not safe for production. "
                f"Set YOOKASSA_RETURN_URL to a public HTTPS URL."
            )
        return url

    def get_yookassa_webhook_url(self) -> str | None:
        """Return YooKassa webhook URL with validation."""
        url = self.yookassa_webhook_url
        if not url:
            return None
        if self.is_production and not self.is_safe_web_url(url):
            raise ValueError(
                f"YooKassa webhook_url '{url}' is not safe for production. "
                f"Set YOOKASSA_WEBHOOK_URL to a public HTTPS URL."
            )
        return url


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""

    return Settings()
