"""version: 1.1.0
description: Deployment status, version metadata, backups, logs, and update triggers.
updated: 2026-05-15
"""

import asyncio
import json
import shlex
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.schemas.deployment import BackupInfo, CurrentVersion, DeploymentStatus, UpdateCheckResult


class DeploymentService:
    """Read deployment state and safely trigger fixed production update commands."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.project_dir = Path(self.settings.deploy_project_dir)
        self.runtime_dir = Path(self.settings.deploy_runtime_dir)
        self.log_dir = Path(self.settings.deploy_log_dir)
        self.backup_dir = Path(self.settings.backup_dir)
        self.metadata_file = Path(self.settings.deploy_metadata_file)
        self.trigger_file = Path(self.settings.deploy_update_trigger_file)

    async def current_version(self) -> CurrentVersion:
        metadata = self._read_json(self.metadata_file)
        if metadata is not None:
            return CurrentVersion(
                version=str(metadata.get("version") or self._fallback_version()),
                branch=str(metadata.get("branch") or "не определено"),
                commit=str(
                    metadata.get("commit_short") or metadata.get("commit") or "не определено"
                ),
                last_commit_message=str(metadata.get("last_commit_message") or "не определено"),
                updated_at=str(metadata.get("updated_at") or "не определено"),
                source="deploy_metadata",
            )
        version = self._fallback_version()
        branch = await self._git(["rev-parse", "--abbrev-ref", "HEAD"], default="не определено")
        commit = await self._git(["rev-parse", "--short", "HEAD"], default="не определено")
        last_commit_message = await self._git(
            ["log", "-1", "--format=%s"],
            default="не определено",
        )
        updated_at = await self._git(["log", "-1", "--format=%ci"], default="не определено")
        return CurrentVersion(
            version=version,
            branch=branch,
            commit=commit,
            last_commit_message=last_commit_message,
            updated_at=updated_at,
            source="version_git_fallback",
        )

    async def check_updates(self) -> UpdateCheckResult:
        branch = await self._git(["rev-parse", "--abbrev-ref", "HEAD"], default="main")
        current = await self._git(["rev-parse", "HEAD"], default="unknown")
        await self._git(["fetch", "origin", branch], default="")
        remote = await self._git(["rev-parse", f"origin/{branch}"], default=current)
        return UpdateCheckResult(
            branch=branch,
            current_commit=current,
            remote_commit=remote,
            has_updates=current != remote,
            checked_at=datetime.now(tz=UTC),
        )

    def read_last_status(self) -> DeploymentStatus | None:
        status_path = self.runtime_dir / "last_update_status.json"
        if not status_path.exists():
            return None
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return DeploymentStatus.from_mapping(
                {
                    "status": "unknown",
                    "message": "Файл статуса обновления повреждён или недоступен.",
                }
            )
        if not isinstance(data, dict):
            return DeploymentStatus.from_mapping(
                {"status": "unknown", "message": "Файл статуса имеет неверный формат."}
            )
        return DeploymentStatus.from_mapping(data)

    def read_update_log_tail(self, lines: int = 40) -> str:
        log_path = self.log_dir / "update.log"
        if not log_path.exists():
            return "Лог обновления пока отсутствует."
        try:
            content = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return "Не удалось прочитать лог обновления."
        tail = "\n".join(content[-lines:])
        if len(tail) > 3500:
            return tail[-3500:]
        return tail or "Лог обновления пуст."

    def list_backups(self, limit: int = 5) -> list[BackupInfo]:
        meta_dir = self.backup_dir / "meta"
        if not meta_dir.exists():
            return []
        backups: list[BackupInfo] = []
        for path in sorted(meta_dir.glob("backup_*.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            db_path = Path(str(data.get("db_backup_path") or ""))
            env_path_raw = data.get("env_backup_path")
            env_path = str(env_path_raw) if env_path_raw else None
            size = db_path.stat().st_size if db_path.exists() else 0
            backups.append(
                BackupInfo(
                    created_at=str(data.get("created_at") or ""),
                    git_commit=str(data.get("git_commit") or "unknown"),
                    git_branch=str(data.get("git_branch") or "unknown"),
                    app_version=str(data.get("app_version") or "unknown"),
                    db_backup_path=str(db_path),
                    env_backup_path=env_path,
                    metadata_path=path,
                    size_bytes=size,
                )
            )
            if len(backups) >= limit:
                break
        return backups

    async def start_update(self, admin_telegram_id: int) -> str:
        if not self.settings.enable_telegram_deploy_commands:
            await self._write_action_log(
                admin_telegram_id,
                "START_UPDATE",
                "disabled",
                {"reason": "ENABLE_TELEGRAM_DEPLOY_COMMANDS=false"},
            )
            return (
                "Запуск обновления из Telegram отключён в настройках сервера. "
                "Используйте GitHub Actions или deploy/update.sh на сервере."
            )
        lock_path = self.runtime_dir / "update.lock"
        if lock_path.exists():
            await self._write_action_log(admin_telegram_id, "START_UPDATE", "locked", {})
            return "Обновление уже выполняется. Повторный запуск заблокирован."
        if self.settings.telegram_deploy_mode == "trigger":
            return await self._request_host_update(admin_telegram_id)
        if self.settings.telegram_deploy_mode != "command":
            return "Режим обновления из Telegram настроен некорректно."
        command = shlex.split(self.settings.deploy_update_command)
        if not command:
            return "Команда обновления не настроена."
        await self._write_action_log(admin_telegram_id, "START_UPDATE", "started", {})
        await asyncio.create_subprocess_exec(
            *command,
            cwd=self.project_dir,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return "🚀 Обновление запущено. Я пришлю результат после завершения."

    async def _request_host_update(self, admin_telegram_id: int) -> str:
        if self.trigger_file.exists():
            await self._write_action_log(admin_telegram_id, "START_UPDATE", "queued", {})
            return "Обновление уже запрошено и ожидает запуска на сервере."
        self.trigger_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "requested_at": datetime.now(tz=UTC).isoformat(),
            "admin_telegram_id": admin_telegram_id,
            "command": "deploy/update.sh --non-interactive",
        }
        tmp_path = self.trigger_file.with_suffix(".tmp")
        await asyncio.to_thread(
            tmp_path.write_text,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            "utf-8",
        )
        tmp_path.replace(self.trigger_file)
        await self._write_action_log(
            admin_telegram_id,
            "START_UPDATE",
            "trigger_created",
            {"trigger_file": str(self.trigger_file)},
        )
        return (
            "🚀 Обновление запрошено.\n\n"
            "Хост-сервис deploy подхватит запрос и запустит безопасное обновление сервера. "
            "Результат будет отправлен администраторам после завершения."
        )

    def format_status(self, status: DeploymentStatus | None) -> str:
        if status is None:
            return "🧾 Статус последнего деплоя\n\nДанных о деплое пока нет."
        icon = "✅" if status.status == "success" else "❌" if status.status == "failed" else "ℹ"
        return (
            f"{icon} Статус последнего деплоя\n\n"
            f"Статус: {status.status}\n"
            f"Ветка: {status.branch or 'н/д'}\n"
            f"Было: {self._short(status.previous_commit)}\n"
            f"Стало: {self._short(status.new_commit)}\n"
            f"Backup: {'создан' if status.backup_created else 'нет'}\n"
            f"Миграции: {'применены' if status.migrations_applied else 'нет'}\n"
            f"Healthcheck: {'успешно' if status.healthcheck_passed else 'нет'}\n"
            f"Начало: {status.started_at or 'н/д'}\n"
            f"Завершение: {status.finished_at or 'н/д'}\n\n"
            f"{status.message or 'Без сообщения.'}"
        )

    def format_deploy_notification(self, status: DeploymentStatus | None) -> str:
        if status is None:
            return "ℹ MP Control: статус обновления недоступен."
        if status.status == "success":
            title = "✅ MP Control успешно обновлён"
        elif status.status == "failed":
            title = "❌ Ошибка обновления MP Control"
        else:
            title = "ℹ Обновление MP Control"
        return (
            f"{title}\n\n"
            f"Ветка: {status.branch or 'н/д'}\n"
            f"Было: {self._short(status.previous_commit)}\n"
            f"Стало: {self._short(status.new_commit)}\n\n"
            f"Миграции: {'применены' if status.migrations_applied else 'не применены'}\n"
            f"Backup: {'создан' if status.backup_created else 'не создан'}\n"
            f"Healthcheck: {'успешно' if status.healthcheck_passed else 'ошибка/не выполнен'}\n\n"
            f"Дата: {status.finished_at or 'н/д'}\n"
            f"Сообщение: {status.message or 'Без сообщения.'}"
        )

    async def _git(self, args: list[str], default: str) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                *args,
                cwd=self.project_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _stderr = await process.communicate()
        except OSError:
            return default
        if process.returncode != 0:
            return default
        return stdout.decode("utf-8", errors="replace").strip() or default

    async def _write_action_log(
        self,
        admin_telegram_id: int,
        action_type: str,
        status: str,
        metadata: dict[str, Any],
    ) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "created_at": datetime.now(tz=UTC).isoformat(),
            "admin_telegram_id": admin_telegram_id,
            "action_type": action_type,
            "status": status,
            "metadata": metadata,
        }
        line = json.dumps(payload, ensure_ascii=False)
        await asyncio.to_thread(
            self._append_text,
            self.runtime_dir / "deployment_actions.log",
            f"{line}\n",
        )

    @staticmethod
    def _append_text(path: Path, text: str) -> None:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(text)

    @staticmethod
    def _read_text(path: Path, default: str) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return default

    def _fallback_version(self) -> str:
        version = self._read_text(self.project_dir / "VERSION", default="").strip()
        if version:
            return version
        local_version = self._read_text(Path("VERSION"), default="").strip()
        return local_version or "не определено"

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _short(value: str | None) -> str:
        if not value:
            return "н/д"
        return value[:7]
