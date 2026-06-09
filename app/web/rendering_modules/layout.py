"""version: 1.0.0
description: Full-page HTML layout rendering for MP Control web cabinet.
updated: 2026-06-09
"""

# ruff: noqa: E501

from html import escape

from app.web.rendering_modules.navigation import _nav
from app.web.rendering_modules.scripts import _js
from app.web.rendering_modules.styles import _css

__all__ = [
    "page",
]


def page(
    title: str,
    user_name: str,
    content: str,
    *,
    active_path: str = "/web/",
    current_user: object | None = None,
    is_admin: bool | None = None,
    user_role: str | None = None,
) -> str:
    if current_user is None or is_admin is None or user_role is None:
        try:
            from app.web.dependencies import (
                CURRENT_WEB_USER,
                current_user_role,
                is_admin_user,
            )

            context_user = CURRENT_WEB_USER.get()
            current_user = current_user or context_user
            if is_admin is None:
                is_admin = is_admin_user(context_user)
            if user_role is None:
                user_role = current_user_role(context_user)
        except Exception:
            if is_admin is None:
                is_admin = False
            if user_role is None:
                user_role = "user"
    safe_title = escape(title)
    safe_user = escape(user_name or "селлер")
    show_admin_nav = bool(is_admin)
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title} — MP Control</title>
  <style>{_css()}</style>
</head>
<body>
  <div id="interface-error" class="interface-error" role="alert" hidden>
    Не удалось загрузить интерфейс. Обновите страницу или войдите заново.
  </div>
  <div class="shell">
    <aside id="sidebar">
      <div class="brand">
        <span class="brand-icon">MP</span>
        <span class="brand-text">Control</span>
      </div>
      <nav>
        {_nav(active_path, show_admin_nav)}
      </nav>
    </aside>
    <div class="main-wrap">
      <header class="topbar">
        <button class="sidebar-toggle" type="button" aria-label="Меню">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        </button>
        <div class="topbar-title">
          <h1>{safe_title}</h1>
        </div>
        <div class="topbar-meta">
          <span class="user-pill">{safe_user}</span>
          <a class="btn btn-ghost btn-sm" href="/web/logout">Выйти</a>
        </div>
      </header>
      <main class="page-fade-in">
        {content}
      </main>
    </div>
  </div>
  <script>{_js()}</script>
</body>
</html>"""
