"""version: 1.0.0
description: Регрессии для public UI и production hardening.
updated: 2026-06-07
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app


def test_root_serves_public_landing() -> None:
    app = create_app()

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "MP Control" in response.text
    assert "Открыть кабинет" in response.text


def test_public_footer_does_not_expose_api_domain() -> None:
    html = Path("public/index.html").read_text(encoding="utf-8")

    assert "api.mpcontrol.online" not in html


def test_admin_manual_sync_uses_queue_not_direct_worker_call() -> None:
    source = Path("app/web/route_modules/admin_visibility.py").read_text(encoding="utf-8")

    assert "await getattr(tasks, task_name)" not in source
    assert "enqueue_job(" in source


def test_backup_requires_encryption_for_production_file_archive() -> None:
    source = Path("scripts/backup_daily.sh").read_text(encoding="utf-8")

    assert "BACKUP_ALLOW_PLAINTEXT_SECRETS" in source
    assert "BACKUP_ENCRYPTION_ENABLED=1" in source
    assert "Security check" in source
    assert "Production requires encryption or explicit plaintext opt-in" in source


def test_backup_requires_password_when_encryption_enabled() -> None:
    source = Path("scripts/backup_daily.sh").read_text(encoding="utf-8")

    assert '[[ "${BACKUP_ENCRYPTION_ENABLED:-0}" == "1"' in source
    assert "BACKUP_ENCRYPTION_PASSWORD is empty" in source


def test_env_example_defaults_to_encrypted_backups() -> None:
    source = Path(".env.example").read_text(encoding="utf-8")

    assert "BACKUP_ENABLED=1" in source
    assert "BACKUP_ENCRYPTION_ENABLED=1" in source
    assert "BACKUP_ENCRYPTION_PASSWORD=" in source
    assert "BACKUP_ALLOW_PLAINTEXT_SECRETS=0" in source
    assert "BACKUP_RETENTION_DAYS=14" in source


def test_restore_supports_encrypted_backup_members() -> None:
    source = Path("scripts/restore.sh").read_text(encoding="utf-8")

    assert "decrypt_if_needed" in source
    assert "BACKUP_ENCRYPTION_PASSWORD" in source
    assert "*.sql.gz.gpg" in source
    assert "mpcontrol_files_*.tar.gz.gpg" in source


def test_logrotate_config_keeps_48_hour_window() -> None:
    source = Path("deploy/logrotate/mpcontrol").read_text(encoding="utf-8")

    assert "daily" in source
    assert "rotate 2" in source
    assert "/opt/mpcontrol/logs/*.log" in source
