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
    integrity: bool | None


@router.get("/admin/backups", response_class=HTMLResponse)
async def admin_backups_page(
    request: Request,
    user: User = ADMIN_WEB_USER_DEPENDENCY,
) -> str:
    settings = get_settings()
    script_path = Path(settings.deploy_project_dir) / "scripts" / "backup_daily.sh"
    backup_dir = Path(settings.backup_dir)
    daily_dir = backup_dir / "daily"

    diagnostics = _collect_diagnostics(script_path, backup_dir, daily_dir)
    backups = _list_backup_files(daily_dir)
    content = _render_backups_page(backups, diagnostics, request.query_params.get("message"))
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
    mode = settings.backup_run_mode

    script = Path(settings.deploy_project_dir) / "scripts" / "backup_daily.sh"

    if mode == "disabled":
        return RedirectResponse(
            "/web/admin/backups?message=Запуск бэкапа доступен только на сервере. "
            "Выполните команду: sudo systemctl start mpcontrol-backup.service",
            status_code=303,
        )

    if mode == "systemd":
        return RedirectResponse(
            "/web/admin/backups?message=Запуск через systemd. "
            "Выполните на сервере: sudo systemctl start mpcontrol-backup.service",
            status_code=303,
        )

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


def _collect_diagnostics(
    script_path: Path, backup_dir: Path, daily_dir: Path
) -> dict[str, object]:
    diag: dict[str, object] = {}
    diag["script_path"] = str(script_path)
    diag["script_exists"] = script_path.exists()
    diag["backup_dir"] = str(backup_dir)
    diag["backup_dir_exists"] = backup_dir.exists()
    diag["daily_dir"] = str(daily_dir)
    diag["daily_dir_exists"] = daily_dir.exists()

    if daily_dir.exists():
        all_files = [f for f in daily_dir.iterdir() if f.is_file()]
        diag["daily_file_count"] = len(all_files)
    else:
        diag["daily_file_count"] = 0

    return diag


def _list_backup_files(daily_dir: Path, limit: int = 30) -> list[BackupFile]:
    if not daily_dir.exists():
        return []
    files: list[BackupFile] = []
    for path in sorted(daily_dir.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
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
                integrity=_check_integrity(path),
            )
        )
        if len(files) >= limit:
            break
    return files


def _render_backups_page(
    backups: list[BackupFile], diagnostics: dict[str, object], message: str | None
) -> str:
    latest_db = next((item for item in backups if item.kind == "db"), None)
    notices: list[str] = []
    if message:
        notices.append(f'<div class="notice success">{_h(message)}</div>')

    # Диагностика
    if not diagnostics.get("script_exists"):
        notices.append(
            f'<div class="notice danger">Скрипт <strong>{_h(str(diagnostics.get("script_path", "")))}</strong> '
            f"не найден на сервере. Бэкапы через веб-интерфейс невозможны.</div>"
        )
    if not diagnostics.get("daily_dir_exists"):
        notices.append(
            f'<div class="notice warning">Каталог бэкапов <strong>{_h(str(diagnostics.get("daily_dir", "")))}</strong> '
            f"не существует. Создайте его: <code>mkdir -p {_h(str(diagnostics.get('daily_dir', '')))}</code></div>"
        )
    elif diagnostics.get("daily_file_count", 0) == 0:
        notices.append(
            f'<div class="notice warning">Каталог <strong>{_h(str(diagnostics.get("daily_dir", "")))}</strong> '
            f"существует, но не содержит файлов бэкапов.</div>"
        )

    if not backups:
        notices.append('<div class="notice warning">Бэкапы не найдены.</div>')
    if latest_db is not None:
        if latest_db.created_at < datetime.now(tz=UTC) - timedelta(hours=24):
            notices.append('<div class="notice warning">Последний бэкап БД старше 24 часов.</div>')
        if latest_db.size_bytes <= 1024:
            notices.append(
                '<div class="notice danger">Последний бэкап БД подозрительно маленький.</div>'
            )

    rows = "".join(
        "<tr>"
        f"<td>{_dt(item.created_at)}</td>"
        f"<td>{_h(item.kind)}</td>"
        f"<td>{_h(item.path.name)}</td>"
        f"<td>{_size(item.size_bytes)}</td>"
        f"<td>{_integrity_label(item.integrity, item.path)}</td>"
        f"<td><code>{_h(str(item.path))}</code></td>"
        "</tr>"
        for item in backups
    )

    run_mode = get_settings().backup_run_mode
    if run_mode in ("disabled", "systemd"):
        run_button = (
            '<button class="btn btn-secondary" type="button" disabled title="Доступно только на сервере">'
            "Создать бэкап сейчас</button>"
            f"<p class='muted' style='margin-top: 0.5rem'>Для запуска на сервере: "
            f"<code>sudo systemctl start mpcontrol-backup.service</code></p>"
        )
    else:
        run_button = (
            '<form method="post" action="/web/admin/backups/run">'
            '<button class="btn btn-primary" type="submit">Создать бэкап сейчас</button>'
            "</form>"
        )

    return f"""
    <div class="page-header">
      <div>
        <h2>Бэкапы</h2>
        <div class="summary-strip">
          <span>Каталог: <strong>{_h(str(diagnostics.get("daily_dir", "")))}</strong></span>
          <span>Скрипт: <strong>{_h(str(diagnostics.get("script_path", "")))}</strong> —
            {"найден" if diagnostics.get("script_exists") else "не найден"}</span>
          <span>Файлов в каталоге: <strong>{diagnostics.get("daily_file_count", 0)}</strong></span>
        </div>
      </div>
      <div class="page-actions">{run_button}</div>
    </div>
    {"".join(notices)}
    <div class="band">
      <h3>Последние бэкапы</h3>
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>Дата</th><th>Тип</th><th>Файл</th><th>Размер</th><th>Проверка</th><th>Путь</th></tr></thead>
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


def _check_integrity(path: Path) -> bool | None:
    name = path.name
    suffix = path.suffix

    # Encrypted files — не проверяем
    if suffix == ".enc" or name.endswith(".gpg"):
        return None

    # Custom dump — не проверяем gzip
    if suffix == ".dump":
        return None

    # .sql.gz — проверяем gzip
    if suffix == ".gz" or name.endswith(".tar.gz"):
        try:
            with gzip.open(path, "rb") as fh:
                fh.read(1)
        except OSError:
            return False
        return True

    return None


def _dt(value: datetime) -> str:
    return value.astimezone().strftime("%d.%m.%Y %H:%M")


def _size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def _integrity_label(value: bool | None, path: Path) -> str:
    name = path.name
    if name.endswith(".enc") or name.endswith(".gpg"):
        return "зашифрован"
    if path.suffix == ".dump":
        return "требует pg_restore"
    if value is None:
        return "н/д"
    return "успешно" if value else "ошибка"


def _h(value: object) -> str:
    from html import escape

    return escape("" if value is None else str(value), quote=True)
