import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UPDATE_SCRIPT = REPO_ROOT / "deploy" / "update.sh"


@lru_cache
def _find_usable_bash() -> str | None:
    candidates: list[str | None] = []
    if os.name == "nt":
        candidates.extend(
            [
                r"C:\Program Files\Git\bin\bash.exe",
                r"C:\Program Files\Git\usr\bin\bash.exe",
            ]
        )
    candidates.append(shutil.which("bash"))
    for candidate in candidates:
        if not candidate:
            continue
        probe = subprocess.run(
            [candidate, "-lc", "true"],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if probe.returncode == 0:
            return candidate
    return None


def _posix(path: Path) -> str:
    return path.resolve().as_posix()


def _env_text(
    *,
    api_base_url: str = "https://app.mpcontrol.online",
    web_app_base_url: str = "https://app.mpcontrol.online",
    web_base_url: str = "https://app.mpcontrol.online",
    public_site_url: str = "https://mpcontrol.online",
    yookassa_webhook_url: str = "https://app.mpcontrol.online/webhooks/yookassa",
    deploy_project_dir: str = "/opt/mpcontrol",
    deploy_log_dir: str = "/opt/mpcontrol/logs/deploy",
    deploy_runtime_dir: str = "/opt/mpcontrol/runtime",
    backup_dir: str = "/opt/mpcontrol/backups",
) -> str:
    return "\n".join(
        [
            "APP_ENV=production",
            "APP_SECRET_KEY=secret",
            "ENCRYPTION_KEY=secret",
            "BOT_TOKEN=123:token",
            "ADMIN_TELEGRAM_IDS=1",
            "POSTGRES_DB=mpcontrol",
            "POSTGRES_USER=mpcontrol",
            "POSTGRES_PASSWORD=secret",
            "DATABASE_URL=postgresql+asyncpg://mpcontrol:secret@postgres:5432/mpcontrol",
            "REDIS_URL=redis://redis:6379/0",
            f"WEB_BASE_URL={web_base_url}",
            f"WEB_APP_BASE_URL={web_app_base_url}",
            f"API_BASE_URL={api_base_url}",
            f"PUBLIC_SITE_URL={public_site_url}",
            "BOT_WEBHOOK_BASE_URL=https://bot.mpcontrol.online",
            "YOOKASSA_RETURN_URL=https://app.mpcontrol.online/payment/success",
            f"YOOKASSA_WEBHOOK_URL={yookassa_webhook_url}",
            f"DEPLOY_PROJECT_DIR={deploy_project_dir}",
            f"DEPLOY_LOG_DIR={deploy_log_dir}",
            f"DEPLOY_RUNTIME_DIR={deploy_runtime_dir}",
            f"BACKUP_DIR={backup_dir}",
            "",
        ]
    )


def _run_validate(tmp_path: Path, env_text: str) -> subprocess.CompletedProcess[str]:
    bash = _find_usable_bash()
    if bash is None:
        pytest.skip("usable bash is not available")

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    env_file = project_dir / ".env"
    env_text = env_text.replace("/opt/mpcontrol", _posix(project_dir))
    env_file.write_text(env_text, encoding="utf-8")

    runtime_dir = tmp_path / "runtime"
    log_file = tmp_path / "logs" / "update.log"
    env = os.environ.copy()
    env.update(
        {
            "PROJECT_DIR": _posix(project_dir),
            "ENV_FILE": _posix(env_file),
            "DEPLOY_RUNTIME_DIR": _posix(runtime_dir),
            "LOG_FILE": _posix(log_file),
        }
    )
    env.pop("PUBLIC_HEALTH_URL", None)

    return subprocess.run(
        [bash, _posix(UPDATE_SCRIPT), "--validate-env-only"],
        cwd=_posix(REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def test_production_validation_rejects_api_example_domain(tmp_path: Path) -> None:
    result = _run_validate(
        tmp_path,
        _env_text(api_base_url="https://api.example.com"),
    )

    assert result.returncode == 1
    assert (
        "Production .env contains placeholder domain in API_BASE_URL=https://api.example.com"
        in result.stderr + result.stdout
    )


def test_production_validation_rejects_web_base_example_domain(tmp_path: Path) -> None:
    result = _run_validate(
        tmp_path,
        _env_text(api_base_url="", web_app_base_url="", web_base_url="https://example.com"),
    )

    assert result.returncode == 1
    assert (
        "Production .env contains placeholder domain in WEB_BASE_URL=https://example.com"
        in result.stderr + result.stdout
    )


def test_production_validation_rejects_yookassa_webhook_example_domain(
    tmp_path: Path,
) -> None:
    result = _run_validate(
        tmp_path,
        _env_text(yookassa_webhook_url="https://example.com/webhooks/yookassa"),
    )

    assert result.returncode == 1
    assert (
        "Production .env contains placeholder domain in YOOKASSA_WEBHOOK_URL=https://example.com/webhooks/yookassa"
        in result.stderr + result.stdout
    )


def test_production_validation_accepts_mpcontrol_api_domain(tmp_path: Path) -> None:
    result = _run_validate(tmp_path, _env_text())

    assert result.returncode == 0
    assert (
        "Public API healthcheck URL resolved from API_BASE_URL: https://app.mpcontrol.online/health"
        in result.stdout
    )


def test_public_healthcheck_url_uses_api_base_url(tmp_path: Path) -> None:
    result = _run_validate(
        tmp_path,
        _env_text(
            api_base_url="https://api.mpcontrol.online",
            web_app_base_url="https://app.mpcontrol.online",
        ),
    )

    assert result.returncode == 0
    assert (
        "Public API healthcheck URL resolved from API_BASE_URL: https://api.mpcontrol.online/health"
        in result.stdout
    )


def test_public_healthcheck_url_falls_back_to_web_app_base_url(tmp_path: Path) -> None:
    result = _run_validate(
        tmp_path,
        _env_text(api_base_url="", web_app_base_url="https://app.mpcontrol.online"),
    )

    assert result.returncode == 0
    assert (
        "Public API healthcheck URL resolved from WEB_APP_BASE_URL: https://app.mpcontrol.online/health"
        in result.stdout
    )


def test_public_healthcheck_url_falls_back_to_web_base_url(tmp_path: Path) -> None:
    result = _run_validate(
        tmp_path,
        _env_text(
            api_base_url="",
            web_app_base_url="",
            web_base_url="https://app.mpcontrol.online",
        ),
    )

    assert result.returncode == 0
    assert (
        "Public API healthcheck URL resolved from WEB_BASE_URL: https://app.mpcontrol.online/health"
        in result.stdout
    )


def test_public_healthcheck_url_falls_back_to_public_site_url(tmp_path: Path) -> None:
    result = _run_validate(
        tmp_path,
        _env_text(
            api_base_url="",
            web_app_base_url="",
            web_base_url="",
            public_site_url="https://mpcontrol.online",
        ),
    )

    assert result.returncode == 0
    assert (
        "Public API healthcheck URL resolved from PUBLIC_SITE_URL: https://mpcontrol.online/health"
        in result.stdout
    )


def test_public_healthcheck_url_requires_one_public_base_url(tmp_path: Path) -> None:
    result = _run_validate(
        tmp_path,
        _env_text(
            api_base_url="",
            web_app_base_url="",
            web_base_url="",
            public_site_url="",
        ),
    )

    assert result.returncode == 1
    assert "Missing public healthcheck URL" in result.stderr + result.stdout


def test_production_validation_rejects_example_deploy_path(tmp_path: Path) -> None:
    result = _run_validate(
        tmp_path,
        _env_text(deploy_project_dir="/opt/example-app"),
    )

    assert result.returncode == 1
    assert (
        "Production .env contains placeholder path /opt/example-app in DEPLOY_PROJECT_DIR"
        in result.stderr + result.stdout
    )
