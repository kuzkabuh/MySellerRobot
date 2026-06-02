"""Admin backup status routes."""

# ruff: noqa: E501

import asyncio
import gzip
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import get_settings
from app.models.domain import User
from app.web.dependencies import ADMIN_WEB_USER_DEPENDENCY
from app.web.rendering import page

router = APIRouter()


@dataclass(slots=True)
class BackupFile:
    path: Path
    kind: str
    created_at: datetime
    size_bytes: int
    gzip_ok: bool | None


@router.get("/admin/backups", response_class=HTMLResponse)
async def admin_backups_page(
    request: Request,
    user: User = ADMIN_WEB_USER_DEPENDENCY,
) -> str:
    backups = _list_backup_files()
    content = _render_backups_page(backups, request.query_params.get("message"))
    return page(
        "Бэкапы",
        user.first_name or user.username or str(user.telegram_id),
        content,
        active_path="/web/admin/backups",
        current_user=user,
        is_admin=True,
        user_role=getattr(user, "role", "admin"),
    )


@router.post("/admin/backups/run")
async def admin_run_backup(
    user: User = ADMIN_WEB_USER_DEPENDENCY,
) -> RedirectResponse:
    del user
    settings = get_settings()
    script = Path(settings.deploy_project_dir) / "scripts" / "backup_daily.sh"
    if not script.exists():
        return RedirectResponse(
            "/web/admin/backups?message=Скрипт backup_daily.sh не найден на сервере",
            status_code=303,
        )
    await asyncio.create_subprocess_exec(
        "bash",
        str(script),
        cwd=settings.deploy_project_dir,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    return RedirectResponse(
        "/web/admin/backups?message=Ручной запуск бэкапа отправлен в фон",
        status_code=303,
    )


def _list_backup_files(limit: int = 30) -> list[BackupFile]:
    root = Path(get_settings().backup_dir) / "daily"
    if not root.exists():
        return []
    files: list[BackupFile] = []
    for path in sorted(root.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
        if not path.is_file():
            continue
        if not path.name.startswith("mpcontrol_"):
            continue
        kind = _backup_kind(path.name)
        if kind is None:
            continue
        files.append(
            BackupFile(
                path=path,
                kind=kind,
                created_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
                size_bytes=path.stat().st_size,
                gzip_ok=_gzip_check(path),
            )
        )
        if len(files) >= limit:
            break
    return files


def _render_backups_page(backups: list[BackupFile], message: str | None) -> str:
    latest_db = next((item for item in backups if item.kind == "db"), None)
    notices = []
    if message:
        notices.append(f'<div class="notice success">{_h(message)}</div>')
    if not backups:
        notices.append('<div class="notice warning">Бэкапы не найдены.</div>')
    if latest_db is not None:
        if latest_db.created_at < datetime.now(tz=UTC) - timedelta(hours=24):
            notices.append('<div class="notice warning">Последний бэкап БД старше 24 часов.</div>')
        if latest_db.size_bytes <= 1024:
            notices.append('<div class="notice danger">Последний бэкап БД подозрительно маленький.</div>')
    rows = "".join(
        "<tr>"
        f"<td>{_dt(item.created_at)}</td>"
        f"<td>{_h(item.kind)}</td>"
        f"<td>{_h(item.path.name)}</td>"
        f"<td>{_size(item.size_bytes)}</td>"
        f"<td>{_gzip_label(item.gzip_ok)}</td>"
        f"<td><code>{_h(str(item.path))}</code></td>"
        "</tr>"
        for item in backups
    )
    return f"""
    <div class="page-header">
      <div>
        <h2>Бэкапы</h2>
        <div class="summary-strip"><span>Каталог: <strong>{_h(str(Path(get_settings().backup_dir) / 'daily'))}</strong></span></div>
      </div>
      <div class="page-actions">
        <form method="post" action="/web/admin/backups/run">
          <button class="btn btn-primary" type="submit">Создать бэкап сейчас</button>
        </form>
      </div>
    </div>
    {''.join(notices)}
    <div class="band">
      <h3>Последние бэкапы</h3>
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>Дата</th><th>Тип</th><th>Файл</th><th>Размер</th><th>Проверка gzip</th><th>Путь</th></tr></thead>
          <tbody>{rows or '<tr><td colspan="6"><div class="empty-state">Бэкапы не найдены</div></td></tr>'}</tbody>
        </table>
      </div>
    </div>
    <div class="band">
      <h3>Systemd timer</h3>
      <p class="muted">Проверьте следующий запуск на сервере командой: <code>systemctl list-timers | grep mpcontrol</code></p>
      <p class="muted">Логи backup-сервиса: <code>journalctl -u mpcontrol-backup.service -n 200 --no-pager</code></p>
    </div>
    """


def _backup_kind(name: str) -> str | None:
    if name.startswith("mpcontrol_db_"):
        return "db"
    if name.startswith("mpcontrol_files_"):
        return "files"
    if name.startswith("mpcontrol_full_"):
        return "full"
    return None


def _gzip_check(path: Path) -> bool | None:
    if not (path.suffix == ".gz" or path.name.endswith(".tar.gz")):
        return None
    try:
        with gzip.open(path, "rb") as fh:
            fh.read(1)
    except OSError:
        return False
    return True


def _dt(value: datetime) -> str:
    return value.astimezone().strftime("%d.%m.%Y %H:%M")


def _size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def _gzip_label(value: bool | None) -> str:
    if value is None:
        return "н/д"
    return "успешно" if value else "ошибка"


def _h(value: object) -> str:
    from html import escape

    return escape("" if value is None else str(value), quote=True)
