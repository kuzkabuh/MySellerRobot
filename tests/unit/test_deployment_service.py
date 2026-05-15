"""version: 1.1.0
description: Unit tests for deployment status, version metadata, backups, and updates.
updated: 2026-05-15
"""

import json
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.services.deployment_service import DeploymentService


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        app_secret_key=SecretStr("test-secret"),
        encryption_key=SecretStr("test-encryption"),
        bot_token=SecretStr("123456:test"),
        deploy_project_dir=str(tmp_path),
        deploy_log_dir=str(tmp_path / "logs" / "deploy"),
        deploy_runtime_dir=str(tmp_path / "runtime"),
        backup_dir=str(tmp_path / "backups"),
        deploy_update_trigger_file=str(tmp_path / "runtime" / "telegram_update_request.json"),
        deploy_metadata_file=str(tmp_path / "runtime" / "deploy_metadata.json"),
        enable_telegram_deploy_commands=False,
    )


def test_read_last_status_missing_file(tmp_path: Path) -> None:
    service = DeploymentService(_settings(tmp_path))

    assert service.read_last_status() is None


def test_read_last_status_invalid_json(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "last_update_status.json").write_text("{bad", encoding="utf-8")
    service = DeploymentService(_settings(tmp_path))

    status = service.read_last_status()

    assert status is not None
    assert status.status == "unknown"
    assert "повреждён" in status.message


def test_read_last_status_success(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "last_update_status.json").write_text(
        json.dumps(
            {
                "status": "success",
                "previous_commit": "abc123456",
                "new_commit": "def123456",
                "branch": "main",
                "migrations_applied": True,
                "backup_created": True,
                "healthcheck_passed": True,
                "message": "ok",
            }
        ),
        encoding="utf-8",
    )
    service = DeploymentService(_settings(tmp_path))

    text = service.format_status(service.read_last_status())

    assert "success" in text
    assert "abc1234" in text
    assert "def1234" in text
    assert "Healthcheck: успешно" in text


def test_update_log_tail(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs" / "deploy"
    log_dir.mkdir(parents=True)
    (log_dir / "update.log").write_text("\n".join(f"line {i}" for i in range(60)), encoding="utf-8")
    service = DeploymentService(_settings(tmp_path))

    tail = service.read_update_log_tail(lines=3)

    assert "line 57" in tail
    assert "line 59" in tail
    assert "line 10" not in tail


def test_list_backups_reads_metadata(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    db_dir = backup_dir / "db"
    meta_dir = backup_dir / "meta"
    db_dir.mkdir(parents=True)
    meta_dir.mkdir(parents=True)
    db_path = db_dir / "mpcontrol.sql.gz"
    db_path.write_bytes(b"backup")
    (meta_dir / "backup_2026-05-15_10-00-00.json").write_text(
        json.dumps(
            {
                "created_at": "2026-05-15T10:00:00+03:00",
                "git_commit": "abcdef123456",
                "git_branch": "main",
                "app_version": "1.4.8",
                "db_backup_path": str(db_path),
                "env_backup_path": "",
            }
        ),
        encoding="utf-8",
    )
    service = DeploymentService(_settings(tmp_path))

    backups = service.list_backups()

    assert len(backups) == 1
    assert backups[0].git_commit == "abcdef123456"
    assert backups[0].size_bytes == len(b"backup")


@pytest.mark.asyncio
async def test_start_update_disabled_writes_audit_log(tmp_path: Path) -> None:
    service = DeploymentService(_settings(tmp_path))

    result = await service.start_update(admin_telegram_id=123)

    assert "отключён" in result
    audit_log = tmp_path / "runtime" / "deployment_actions.log"
    assert audit_log.exists()
    assert "START_UPDATE" in audit_log.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_current_version_reads_deploy_metadata(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "deploy_metadata.json").write_text(
        json.dumps(
            {
                "version": "1.4.12",
                "branch": "main",
                "commit": "8d250ca123",
                "commit_short": "8d250ca",
                "last_commit_message": "Версия 1.4.12",
                "updated_at": "2026-05-15T13:45:00+03:00",
            }
        ),
        encoding="utf-8",
    )
    service = DeploymentService(_settings(tmp_path))

    version = await service.current_version()

    assert version.version == "1.4.12"
    assert version.branch == "main"
    assert version.commit == "8d250ca"
    assert version.last_commit_message == "Версия 1.4.12"
    assert version.source == "deploy_metadata"


@pytest.mark.asyncio
async def test_current_version_falls_back_to_version_file(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("1.4.12\n", encoding="utf-8")
    service = DeploymentService(_settings(tmp_path))

    version = await service.current_version()

    assert version.version == "1.4.12"
    assert version.branch == "не определено"
    assert version.source == "version_git_fallback"


@pytest.mark.asyncio
async def test_start_update_creates_host_trigger_when_enabled(tmp_path: Path) -> None:
    settings = _settings(tmp_path).model_copy(
        update={
            "enable_telegram_deploy_commands": True,
            "telegram_deploy_mode": "trigger",
        }
    )
    service = DeploymentService(settings)

    result = await service.start_update(admin_telegram_id=123)

    trigger = tmp_path / "runtime" / "telegram_update_request.json"
    assert "Обновление запрошено" in result
    assert trigger.exists()
    assert "deploy/update.sh --non-interactive" in trigger.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_start_update_reports_existing_trigger(tmp_path: Path) -> None:
    settings = _settings(tmp_path).model_copy(
        update={
            "enable_telegram_deploy_commands": True,
            "telegram_deploy_mode": "trigger",
        }
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "telegram_update_request.json").write_text("{}", encoding="utf-8")
    service = DeploymentService(settings)

    result = await service.start_update(admin_telegram_id=123)

    assert "уже запрошено" in result
