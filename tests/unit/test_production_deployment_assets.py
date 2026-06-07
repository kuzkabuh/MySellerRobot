"""Regression tests for production deployment scripts and configuration."""

from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_env_example_documents_real_secret_generation() -> None:
    env_example = read(".env.example")

    assert "openssl rand -hex 32" in env_example
    assert "Fernet.generate_key()" in env_example
    assert "never change ENCRYPTION_KEY" in env_example
    assert "BOT_WEBHOOK_ENABLED=true" in env_example
    Fernet(Fernet.generate_key())


def test_alembic_version_table_uses_varchar_255() -> None:
    env_py = read("migrations/env.py")

    assert "CREATE TABLE IF NOT EXISTS alembic_version" in env_py
    assert "VARCHAR(255)" in env_py
    assert "ALTER COLUMN version_num TYPE VARCHAR(255)" in env_py
    assert "version_table=\"alembic_version\"" in env_py


def test_install_script_prepares_production_prerequisites() -> None:
    install_sh = read("deploy/install.sh")

    assert "python3-cryptography" in install_sh
    assert "validate_secret_values" in install_sh
    assert "Preparing Alembic version table" in install_sh
    assert "configure_backup_timer" in install_sh
    assert "configure_telegram_webhook" in install_sh
    assert "BOT_WEBHOOK_BASE_URL" in install_sh
    assert "BOT_WEBHOOK_HOST" in install_sh
    assert "prepare_ssl_domains" in install_sh
    assert "verify_bot_certificate_san" in install_sh
    assert "DNS:${BOT_WEBHOOK_HOST}" in install_sh
    assert "getWebhookInfo" in install_sh
    assert "ALTER COLUMN version_num TYPE VARCHAR(255)" in install_sh


def test_readme_documents_bot_ssl_diagnostics() -> None:
    readme = read("README.md")

    assert "bot.mpcontrol.online  -> SERVER_IP" in readme
    assert "DNS:bot.mpcontrol.online" in readme
    assert "openssl s_client -connect bot.mpcontrol.online:443" in readme
    assert "getWebhookInfo" in readme


def test_backup_and_restore_entrypoints_exist() -> None:
    backup_sh = read("scripts/backup.sh")
    restore_sh = read("scripts/restore.sh")

    assert "backup_daily.sh" in backup_sh
    assert "RESTORE_CONFIRM=YES" in restore_sh
    assert "safety_before_restore" in restore_sh
    assert "RESTORE_FILES" in restore_sh


def test_prod_compose_limits_docker_log_growth() -> None:
    compose = read("docker-compose.prod.yml")

    assert "max-size: \"20m\"" in compose
    assert "max-file: \"3\"" in compose
    assert compose.count("logging: *default-logging") >= 5
