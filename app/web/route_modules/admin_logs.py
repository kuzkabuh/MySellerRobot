"""Admin log viewer routes."""

# ruff: noqa: E501

import logging
from datetime import datetime
from html import escape

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from app.models.domain import User
from app.services.log_viewer_service import LogViewerService
from app.web.dependencies import CURRENT_WEB_USER_DEPENDENCY, is_admin_user
from app.web.rendering import page

router = APIRouter()
logger = logging.getLogger(__name__)


def _require_admin(user: User) -> None:
    if not is_admin_user(user):
        logger.warning(
            "admin_logs_unauthorized_access",
            extra={"user_id": user.id, "telegram_id": user.telegram_id},
        )
        raise HTTPException(status_code=403, detail="Доступно только администраторам")


def _name(user: User) -> str:
    return user.first_name or user.username or str(user.telegram_id)


def _h(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _admin_page(title: str, user: User, content: str, active_path: str) -> str:
    return page(title, f"{_name(user)} (admin)", content, active_path=active_path)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def _level_badge(level: str) -> str:
    level_upper = level.upper()
    cls_map = {
        "DEBUG": "",
        "INFO": "action",
        "WARNING": "warn",
        "ERROR": "bad",
        "CRITICAL": "bad",
    }
    cls = cls_map.get(level_upper, "")
    return f'<span class="badge {cls}">{_h(level_upper)}</span>'


@router.get("/admin/logs", response_class=HTMLResponse)
async def admin_logs_page(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    log_file: str = Query(default="app.log"),
    level: str = Query(default=""),
    search: str = Query(default=""),
    limit: int = Query(default=100),
) -> str:
    _require_admin(user)

    service = LogViewerService()
    log_files = service.list_log_files()
    if log_file not in log_files:
        log_file = "app.log"

    stats_cards = []
    for fname in log_files:
        try:
            stats = service.get_stats(fname)
            stats_cards.append(
                f'<div class="kpi">'
                f"<span>{_h(fname)}</span>"
                f"<strong>{_format_size(stats.file_size)}</strong>"
                f'<div class="muted">{stats.total_lines} строк</div>'
                f"</div>"
            )
        except FileNotFoundError:
            stats_cards.append(
                f'<div class="kpi warn"><span>{_h(fname)}</span><strong>не найден</strong></div>'
            )

    try:
        app_stats = service.get_stats("app.log")
        error_count = app_stats.level_counts.get("ERROR", 0)
        critical_count = app_stats.level_counts.get("CRITICAL", 0)
        stats_cards.extend(
            [
                f'<div class="kpi bad">'
                f"<span>ERROR за всё время</span>"
                f"<strong>{error_count}</strong>"
                f"</div>",
                f'<div class="kpi bad">'
                f"<span>CRITICAL за всё время</span>"
                f"<strong>{critical_count}</strong>"
                f"</div>",
            ]
        )
    except FileNotFoundError:
        pass

    file_tabs = "".join(
        f'<a class="{"active" if f == log_file else ""}" '
        f'href="/web/admin/logs?log_file={f}&level={_h(level)}&search={_h(search)}&limit={limit}">'
        f"{_h(f)}</a>"
        for f in log_files
    )

    level_options = "".join(
        f'<option value="{lvl}" {"selected" if lvl == level else ""}>{lvl}</option>'
        for lvl in ["", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    )

    limit_options = "".join(
        f'<option value="{n}" {"selected" if n == limit else ""}>{n}</option>'
        for n in [100, 500, 1000, 5000]
    )
    archive_button = (
        f'<button class="btn" onclick="archiveLog(\'{_h(log_file)}\')">Архивировать и очистить</button>'
        if log_file in {"app.log", "errors.log"}
        else ""
    )

    content = f"""
    <style>
    .log-table td {{ font-family: var(--font-mono); font-size: 12px; }}
    .log-table .timestamp {{ white-space: nowrap; color: var(--text-muted); }}
    .log-table .logger {{ color: var(--text-secondary); max-width: 200px; overflow: hidden; text-overflow: ellipsis; }}
    .log-table .message {{ word-break: break-word; }}
    .log-modal-body {{ font-family: var(--font-mono); font-size: 12px; white-space: pre-wrap; word-break: break-word; max-height: 60vh; overflow-y: auto; background: var(--bg-muted); padding: 16px; border-radius: var(--radius); }}
    .log-modal-traceback {{ margin-top: 16px; padding: 16px; background: var(--danger-soft); border-radius: var(--radius); }}
    .log-controls {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
    .auto-refresh-indicator {{ display: none; align-items: center; gap: 4px; color: var(--success); font-size: 12px; }}
    .auto-refresh-indicator.active {{ display: flex; }}
    .auto-refresh-indicator::before {{ content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--success); animation: pulse 1s infinite; }}
    @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.3; }} }}
    </style>

    <div class="page-header">
      <div>
        <h2>Логи системы</h2>
        <div class="summary-strip">
          <span>Просмотр и анализ логов приложения</span>
        </div>
      </div>
      <div class="page-actions">
        <a class="btn" href="/web/admin/logs/download/{log_file}">Скачать {_h(log_file)}</a>
        {archive_button}
      </div>
    </div>

    <div class="kpi-grid">
      {"".join(stats_cards)}
    </div>

    <div class="subnav">
      {file_tabs}
    </div>

    <form class="filters" method="get" id="log-filters">
      <input type="hidden" name="log_file" value="{_h(log_file)}">
      <div>
        <label>Уровень</label>
        <select name="level">{level_options}</select>
      </div>
      <div>
        <label>Поиск</label>
        <input name="search" value="{_h(search)}" placeholder="Текст для поиска">
      </div>
      <div>
        <label>Строк</label>
        <select name="limit">{limit_options}</select>
      </div>
      <button class="btn btn-primary" type="submit">Применить</button>
    </form>

    <div class="log-controls" style="margin-bottom: 12px;">
      <button class="btn" onclick="refreshLogs()">Обновить</button>
      <label style="display: flex; align-items: center; gap: 8px; margin: 0;">
        <input type="checkbox" id="auto-refresh-toggle" onchange="toggleAutoRefresh()">
        Автообновление
      </label>
      <select id="auto-refresh-interval" onchange="updateAutoRefreshInterval()" style="width: auto;">
        <option value="5">5 сек</option>
        <option value="10" selected>10 сек</option>
        <option value="30">30 сек</option>
      </select>
      <div class="auto-refresh-indicator" id="auto-refresh-indicator">
        <span>Автообновление активно</span>
      </div>
    </div>

    <div class="table-wrap">
      <table class="table log-table" id="log-table">
        <thead>
          <tr>
            <th>Время</th>
            <th>Уровень</th>
            <th>Модуль</th>
            <th>Пользователь</th>
            <th>Сообщение</th>
            <th></th>
          </tr>
        </thead>
        <tbody id="log-table-body">
          <tr><td colspan="6" class="muted">Загрузка...</td></tr>
        </tbody>
      </table>
    </div>

    <div id="log-modal" style="display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 1000; padding: 24px;">
      <div style="background: var(--bg-card); border-radius: var(--radius-lg); max-width: 900px; margin: 0 auto; max-height: 90vh; overflow-y: auto; padding: 24px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
          <h2 style="margin: 0;">Детали записи</h2>
          <button class="btn" onclick="closeLogModal()">Закрыть</button>
        </div>
        <div id="log-modal-content" class="log-modal-body"></div>
      </div>
    </div>

    <script>
    let autoRefreshTimer = null;
    let autoRefreshInterval = 10;

    function escapeHtml(text) {{
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }}

    function levelBadge(level) {{
      const clsMap = {{ 'DEBUG': '', 'INFO': 'action', 'WARNING': 'warn', 'ERROR': 'bad', 'CRITICAL': 'bad' }};
      const cls = clsMap[level.toUpperCase()] || '';
      return `<span class="badge ${{cls}}">${{escapeHtml(level)}}</span>`;
    }}

    function formatTimestamp(ts) {{
      if (!ts) return '-';
      try {{
        const d = new Date(ts);
        return d.toLocaleString('ru-RU', {{ day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }});
      }} catch {{
        return '-';
      }}
    }}

    function loadLogs() {{
      const params = new URLSearchParams(window.location.search);
      fetch('/web/admin/logs/data?' + params.toString())
        .then(r => r.json())
        .then(data => {{
          const tbody = document.getElementById('log-table-body');
          if (!data.entries || data.entries.length === 0) {{
            tbody.innerHTML = '<tr><td colspan="6" class="muted">Записи не найдены</td></tr>';
            return;
          }}
          tbody.innerHTML = data.entries.map((entry, idx) => `
            <tr>
              <td class="timestamp">${{formatTimestamp(entry.timestamp)}}</td>
              <td>${{levelBadge(entry.level)}}</td>
              <td class="logger" title="${{escapeHtml(entry.logger_name)}}">${{escapeHtml(entry.logger_name)}}</td>
              <td>${{entry.user_id ? 'user:' + entry.user_id : (entry.telegram_id ? 'tg:' + entry.telegram_id : '-')}}</td>
              <td class="message">${{escapeHtml(entry.message.substring(0, 200))}}${{entry.message.length > 200 ? '...' : ''}}</td>
              <td><button class="btn btn-sm" onclick="showLogDetail(${{idx}})">Подробнее</button></td>
            </tr>
          `).join('');
          window._logEntries = data.entries;
        }})
        .catch(err => {{
          console.error('Failed to load logs:', err);
          document.getElementById('log-table-body').innerHTML = '<tr><td colspan="6" class="muted">Ошибка загрузки</td></tr>';
        }});
    }}

    function showLogDetail(idx) {{
      const entry = window._logEntries[idx];
      if (!entry) return;
      let html = `<div><strong>Время:</strong> ${{formatTimestamp(entry.timestamp)}}</div>`;
      html += `<div><strong>Уровень:</strong> ${{entry.level}}</div>`;
      html += `<div><strong>Модуль:</strong> ${{escapeHtml(entry.logger_name)}}</div>`;
      html += `<div><strong>Сообщение:</strong><br>${{escapeHtml(entry.message)}}</div>`;
      if (entry.user_id) html += `<div><strong>User ID:</strong> ${{entry.user_id}}</div>`;
      if (entry.telegram_id) html += `<div><strong>Telegram ID:</strong> ${{entry.telegram_id}}</div>`;
      html += `<div style="margin-top: 16px;"><strong>Raw:</strong><br><pre id="log-raw-text" style="white-space: pre-wrap; word-break: break-word; background: var(--bg-muted); padding: 8px; border-radius: 4px; max-height: 300px; overflow-y: auto;">${{escapeHtml(entry.raw_line)}}</pre></div>`;
      if (entry.traceback) {{
        html += `<div class="log-modal-traceback"><strong>Traceback:</strong><br>${{escapeHtml(entry.traceback)}}</div>`;
      }}
      html += `<button class="btn" style="margin-top: 16px;" onclick="copyRawLog()">Копировать</button>`;
      document.getElementById('log-modal-content').innerHTML = html;
      document.getElementById('log-modal').style.display = 'block';
    }}

    function closeLogModal() {{
      document.getElementById('log-modal').style.display = 'none';
    }}

    function copyRawLog() {{
      const rawElement = document.getElementById('log-raw-text');
      if (!rawElement) {{
        alert('Ошибка: элемент не найден');
        return;
      }}
      const text = rawElement.textContent;
      navigator.clipboard.writeText(text).then(() => {{
        alert('Скопировано');
      }}).catch(err => {{
        console.error('Ошибка копирования:', err);
        alert('Ошибка копирования: ' + err);
      }});
    }}

    function refreshLogs() {{
      loadLogs();
    }}

    function toggleAutoRefresh() {{
      const enabled = document.getElementById('auto-refresh-toggle').checked;
      const indicator = document.getElementById('auto-refresh-indicator');
      if (enabled) {{
        indicator.classList.add('active');
        autoRefreshTimer = setInterval(loadLogs, autoRefreshInterval * 1000);
      }} else {{
        indicator.classList.remove('active');
        if (autoRefreshTimer) {{
          clearInterval(autoRefreshTimer);
          autoRefreshTimer = null;
        }}
      }}
    }}

    function updateAutoRefreshInterval() {{
      autoRefreshInterval = parseInt(document.getElementById('auto-refresh-interval').value);
      if (document.getElementById('auto-refresh-toggle').checked) {{
        if (autoRefreshTimer) clearInterval(autoRefreshTimer);
        autoRefreshTimer = setInterval(loadLogs, autoRefreshInterval * 1000);
      }}
    }}

    function archiveLog(logName) {{
      if (!confirm('Архивировать и очистить ' + logName + '?')) return;
      fetch('/web/admin/logs/archive/' + logName, {{ method: 'POST' }})
        .then(r => r.json())
        .then(data => {{
          if (data.success) {{
            alert('Архивировано: ' + data.archive_name);
            loadLogs();
          }} else {{
            alert('Ошибка: ' + data.error);
          }}
        }})
        .catch(err => alert('Ошибка: ' + err));
    }}

    document.addEventListener('DOMContentLoaded', loadLogs);
    document.addEventListener('keydown', (e) => {{
      if (e.key === 'Escape') closeLogModal();
    }});
    </script>
    """

    return _admin_page("Логи системы", user, content, "/web/admin/logs")


@router.get("/admin/logs/data")
async def admin_logs_data(
    user: User = CURRENT_WEB_USER_DEPENDENCY,
    log_file: str = Query(default="app.log"),
    level: str = Query(default=""),
    search: str = Query(default=""),
    limit: int = Query(default=100),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    user_id: int = Query(default=0),
    telegram_id: int = Query(default=0),
) -> JSONResponse:
    _require_admin(user)

    service = LogViewerService()
    if log_file not in service.list_log_files():
        log_file = "app.log"

    dt_from = None
    dt_to = None
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
        except ValueError:
            pass

    try:
        entries = service.read_logs(
            log_name=log_file,
            limit=limit,
            level=level if level else None,
            search=search if search else None,
            date_from=dt_from,
            date_to=dt_to,
            user_id=user_id if user_id else None,
            telegram_id=telegram_id if telegram_id else None,
        )
    except FileNotFoundError:
        logger_message = "Лог-файл пока не создан или был перенесён в архив."
        return JSONResponse({"entries": [], "count": 0, "message": logger_message})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Недопустимое имя лог-файла") from exc

    return JSONResponse(
        {
            "entries": [
                {
                    "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                    "level": e.level,
                    "logger_name": e.logger_name,
                    "message": e.message,
                    "raw_line": e.raw_line,
                    "user_id": e.user_id,
                    "telegram_id": e.telegram_id,
                    "traceback": e.traceback,
                }
                for e in entries
            ],
            "count": len(entries),
        }
    )


@router.get("/admin/logs/download/{log_name}")
async def admin_logs_download(
    log_name: str,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
) -> FileResponse:
    _require_admin(user)

    service = LogViewerService()
    try:
        log_path, filename = service.download_log(log_name)
        return FileResponse(
            path=log_path,
            filename=filename,
            media_type="application/octet-stream",
        )
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


class ArchiveRequest(BaseModel):
    confirm: bool = True


@router.post("/admin/logs/archive/{log_name}")
async def admin_logs_archive(
    log_name: str,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
) -> JSONResponse:
    _require_admin(user)

    service = LogViewerService()
    try:
        archive_path = service.archive_log(log_name)
        return JSONResponse(
            {
                "success": True,
                "archive_name": archive_path.name,
                "message": f"Лог {log_name} архивирован в {archive_path.name}",
            }
        )
    except (ValueError, FileNotFoundError) as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)


@router.post("/admin/logs/clear/{log_name}")
async def admin_logs_clear(
    log_name: str,
    user: User = CURRENT_WEB_USER_DEPENDENCY,
) -> JSONResponse:
    _require_admin(user)

    service = LogViewerService()
    try:
        service.clear_log(log_name)
        return JSONResponse(
            {
                "success": True,
                "message": f"Лог {log_name} очищен",
            }
        )
    except (ValueError, FileNotFoundError) as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
