"""version: 1.0.0
description: Send deployment status notifications to Telegram administrators.
updated: 2026-05-15
"""

import argparse
import asyncio
import json
from pathlib import Path

from aiogram import Bot

from app.core.config import get_settings
from app.schemas.deployment import DeploymentStatus
from app.services.admin.deployment_service import DeploymentService


async def _send(status_file: Path | None) -> None:
    settings = get_settings()
    if not settings.enable_telegram_deploy_notifications:
        return
    if not settings.admin_ids:
        return
    target = status_file or Path(settings.deploy_runtime_dir) / "last_update_status.json"
    if not target.exists():
        return
    data = json.loads(target.read_text(encoding="utf-8"))
    status = DeploymentStatus.from_mapping(data if isinstance(data, dict) else {})
    service = DeploymentService(settings)
    text = service.format_deploy_notification(status)
    bot = Bot(token=settings.bot_token.get_secret_value())
    try:
        for admin_id in settings.admin_ids:
            await bot.send_message(admin_id, text)
    finally:
        await bot.session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Notify admins about MP Control deployment.")
    parser.add_argument("--status-file", type=Path, default=None)
    args = parser.parse_args()
    asyncio.run(_send(args.status_file))


if __name__ == "__main__":
    main()
