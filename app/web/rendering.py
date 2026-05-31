"""version: 4.0.0
description: Server-side HTML rendering — BI/SaaS design system for MP Control web cabinet.
updated: 2026-05-31
"""

# ruff: noqa: E501

from html import escape

NAV_GROUPS = [
    ("Обзор", [("Главная", "/web/")]),
    (
        "Операции",
        [("Заказы", "/web/orders"), ("Продажи", "/web/sales"), ("Возвраты", "/web/returns")],
    ),
    (
        "Финансы",
        [
            ("Прибыль", "/web/profit"),
            ("План/факт", "/web/plan-fact"),
            ("Безубыточность", "/web/break-even"),
            ("Себестоимость", "/web/costs"),
            ("МРЦ WB", "/web/mrc-pricing"),
            ("Цены и акции", "/web/pricing"),
        ],
    ),
    (
        "Товары",
        [
            ("Товары", "/web/products"),
            ("Сопоставление WB / Ozon", "/web/product-matching"),
            ("Остатки", "/web/stocks"),
        ],
    ),
    (
        "Контроль",
        [
            ("Алерты", "/web/alerts"),
            ("Качество данных", "/web/data-quality"),
            ("Контроль ошибок", "/web/control"),
            ("Аналитика", "/web/analytics"),
        ],
    ),
    (
        "Аккаунт",
        [
            ("Кабинеты МП", "/web/accounts"),
            ("Подписка и тариф", "/web/subscription"),
            ("Профиль и настройки", "/web/profile"),
            ("Настройки", "/web/settings"),
            ("Комиссии МП (admin)", "/web/admin/commissions"),
            ("Тарифы (admin)", "/web/admin/tariffs"),
            ("Промокоды (admin)", "/web/admin/promocodes"),
        ],
    ),
]

NAV_ICONS = {
    "Главная": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 6l6-4 6 4v7a1 1 0 01-1 1H3a1 1 0 01-1-1V6z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M6 14V9h4v5" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>',
    "Заказы": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="2" y="2" width="12" height="12" rx="2" stroke="currentColor" stroke-width="1.5"/><path d="M5 6h6M5 8.5h6M5 11h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "Продажи": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 12l4-4 3 2 5-6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "Возвраты": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M4 8l-2 2 2 2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M2 10h8a4 4 0 000-8H6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "Прибыль": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.5"/><path d="M8 5v6M6.5 6.5h2a1.5 1.5 0 010 3h-2a1.5 1.5 0 000 3h2.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "План/факт": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="2" y="8" width="3" height="6" rx="1" stroke="currentColor" stroke-width="1.5"/><rect x="6.5" y="4" width="3" height="10" rx="1" stroke="currentColor" stroke-width="1.5"/><rect x="11" y="6" width="3" height="8" rx="1" stroke="currentColor" stroke-width="1.5"/></svg>',
    "Безубыточность": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.5"/><path d="M2 8h12" stroke="currentColor" stroke-width="1.5"/></svg>',
    "Себестоимость": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M4 2v12M12 2v12M4 8h8M4 5h8M4 11h8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "МРЦ WB": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 13V3l5 4 5-4v10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "Цены и акции": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M9 2H4a2 2 0 00-2 2v8a2 2 0 002 2h8a2 2 0 002-2V7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M11 2l3 3-6 6H5V8l6-6z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>',
    "Товары": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 4l6-2 6 2v8l-6 2-6-2V4z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M2 4l6 2 6-2M8 6v8" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>',
    "Сопоставление WB / Ozon": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M4 6h8M10 4l2 2-2 2M12 10H4M6 8l-2 2 2 2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "Остатки": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="2" y="6" width="12" height="8" rx="1" stroke="currentColor" stroke-width="1.5"/><path d="M4 6V4a2 2 0 012-2h4a2 2 0 012 2v2" stroke="currentColor" stroke-width="1.5"/></svg>',
    "Алерты": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 2a4 4 0 014 4c0 3 1.5 4.5 2 5H4c.5-.5 2-2 2-5a4 4 0 014-4z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M6.5 13a1.5 1.5 0 003 0" stroke="currentColor" stroke-width="1.5"/></svg>',
    "Качество данных": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M6 8l2 2 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.5"/></svg>',
    "Контроль ошибок": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 2l6 11H2L8 2z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M8 6v3M8 11.5v.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "Аналитика": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.5"/><path d="M8 2v6l4 2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "Кабинеты МП": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="2" y="3" width="12" height="10" rx="2" stroke="currentColor" stroke-width="1.5"/><path d="M5 7h6M5 10h4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "Подписка и тариф": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 4l6 3 6-3M2 4v8l6 3 6-3V4M2 4l6-2 6 2" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>',
    "Профиль и настройки": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="5" r="3" stroke="currentColor" stroke-width="1.5"/><path d="M2 14c0-3 2.5-5 6-5s6 2 6 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "Настройки": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="2" stroke="currentColor" stroke-width="1.5"/><path d="M8 2v2M8 12v2M2 8h2M12 8h2M3.8 3.8l1.4 1.4M10.8 10.8l1.4 1.4M12.2 3.8l-1.4 1.4M5.2 10.8l-1.4 1.4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "Комиссии МП (admin)": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="3" y="2" width="10" height="12" rx="1" stroke="currentColor" stroke-width="1.5"/><path d="M6 5h4M6 8h4M6 11h2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "Тарифы (admin)": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 4l6 3 6-3M2 4v8l6 3 6-3V4M2 4l6-2 6 2" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>',
    "Промокоды (admin)": '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 5h12v6H2zM5 5v6M8 7h3M8 9h2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
}

NAV_ICONS_FALLBACK = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="3" stroke="currentColor" stroke-width="1.5"/></svg>'


def page(title: str, user_name: str, content: str, *, active_path: str = "/web/") -> str:
    safe_title = escape(title)
    safe_user = escape(user_name or "селлер")
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title} — MP Control</title>
  <style>{_css()}</style>
</head>
<body>
  <div class="shell">
    <aside id="sidebar">
      <div class="brand">
        <span class="brand-icon">MP</span>
        <span class="brand-text">Control</span>
      </div>
      <nav>
        {_nav(active_path)}
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
      <main>
        {content}
      </main>
    </div>
  </div>
  <script>{_js()}</script>
</body>
</html>"""


def _css() -> str:
    return """
    :root {
      color-scheme: light;
      --bg: #f5f7fb;
      --bg-card: #ffffff;
      --bg-muted: #f8fafc;
      --bg-hover: #f1f5f9;
      --bg-sidebar: #ffffff;
      --bg-sidebar-active: #eff6ff;
      --bg-sidebar-hover: #f8fafc;
      --text: #0f172a;
      --text-secondary: #475569;
      --text-muted: #94a3b8;
      --border: #e2e8f0;
      --border-light: #f1f5f9;
      --accent: #2563eb;
      --accent-hover: #1d4ed8;
      --accent-soft: #dbeafe;
      --accent-bg: #eff6ff;
      --success: #059669;
      --success-soft: #dcfce7;
      --success-border: #bbf7d0;
      --danger: #dc2626;
      --danger-soft: #fee2e2;
      --danger-border: #fecaca;
      --warning: #d97706;
      --warning-soft: #fef3c7;
      --warning-border: #fde68a;
      --info: #2563eb;
      --info-soft: #dbeafe;
      --wb: #7c3aed;
      --wb-soft: #f5f3ff;
      --wb-border: #ddd6fe;
      --ozon: #2563eb;
      --ozon-soft: #dbeafe;
      --ozon-border: #bfdbfe;
      --shadow-xs: 0 1px 2px rgb(15 23 42 / 0.04);
      --shadow-sm: 0 1px 3px rgb(15 23 42 / 0.06), 0 1px 2px rgb(15 23 42 / 0.04);
      --shadow: 0 4px 6px -1px rgb(15 23 42 / 0.07), 0 2px 4px -2px rgb(15 23 42 / 0.05);
      --shadow-md: 0 10px 15px -3px rgb(15 23 42 / 0.08), 0 4px 6px -4px rgb(15 23 42 / 0.04);
      --shadow-lg: 0 20px 25px -5px rgb(15 23 42 / 0.08), 0 8px 10px -6px rgb(15 23 42 / 0.04);
      --radius-sm: 6px;
      --radius: 10px;
      --radius-lg: 14px;
      --radius-xl: 18px;
      --radius-full: 999px;
      --sidebar-w: 260px;
      --topbar-h: 56px;
      --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', 'Roboto', 'Helvetica Neue', Arial, sans-serif;
      --font-mono: ui-monospace, 'SF Mono', 'Cascadia Code', 'Source Code Pro', Menlo, Consolas, monospace;
    }
    *, *::before, *::after { box-sizing: border-box; }
    html { -webkit-text-size-adjust: 100%; }
    body {
      margin: 0;
      font-family: var(--font);
      background: var(--bg);
      color: var(--text);
      font-size: 14px;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }
    a { color: var(--accent); text-decoration: none; }
    a:hover { color: var(--accent-hover); }
    h1 { font-size: 20px; font-weight: 700; margin: 0; letter-spacing: -0.01em; }
    h2 { font-size: 16px; font-weight: 700; margin: 0 0 12px; letter-spacing: -0.01em; }
    h3 { font-size: 14px; font-weight: 700; margin: 0 0 8px; }
    p { margin: 0 0 8px; }
    .muted { color: var(--text-muted); font-size: 13px; }

    /* ── Shell ── */
    .shell {
      display: grid;
      grid-template-columns: var(--sidebar-w) minmax(0, 1fr);
      min-height: 100vh;
    }
    .main-wrap {
      display: flex;
      flex-direction: column;
      min-width: 0;
      min-height: 100vh;
    }

    /* ── Sidebar ── */
    aside {
      background: var(--bg-sidebar);
      border-right: 1px solid var(--border);
      position: sticky;
      top: 0;
      height: 100vh;
      overflow-y: auto;
      overflow-x: hidden;
      padding: 16px 12px;
      z-index: 100;
      scrollbar-width: thin;
      scrollbar-color: var(--border) transparent;
    }
    aside::-webkit-scrollbar { width: 4px; }
    aside::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 4px 8px 16px;
      margin-bottom: 8px;
      border-bottom: 1px solid var(--border-light);
    }
    .brand-icon {
      display: inline-grid;
      place-items: center;
      width: 34px;
      height: 34px;
      border-radius: var(--radius);
      background: linear-gradient(135deg, #2563eb, #0f766e);
      color: #fff;
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.04em;
      flex-shrink: 0;
    }
    .brand-text {
      font-size: 16px;
      font-weight: 800;
      color: var(--text);
      letter-spacing: -0.02em;
    }
    nav a {
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--text-secondary);
      text-decoration: none;
      padding: 7px 10px;
      border-radius: var(--radius-sm);
      margin-bottom: 1px;
      font-size: 13px;
      font-weight: 500;
      transition: all 0.12s ease;
      line-height: 1.3;
    }
    nav a:hover {
      background: var(--bg-sidebar-hover);
      color: var(--text);
    }
    nav a.active {
      background: var(--bg-sidebar-active);
      color: var(--accent);
      font-weight: 600;
    }
    .nav-icon {
      display: inline-grid;
      place-items: center;
      width: 28px;
      height: 28px;
      flex-shrink: 0;
      border-radius: var(--radius-sm);
      color: var(--text-muted);
      transition: all 0.12s ease;
    }
    nav a:hover .nav-icon { color: var(--text-secondary); }
    nav a.active .nav-icon { color: var(--accent); }
    .nav-group { margin-top: 12px; }
    .nav-group:first-child { margin-top: 0; }
    .nav-title {
      color: var(--text-muted);
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      padding: 4px 10px 6px;
    }

    /* ── Topbar ── */
    .topbar {
      display: flex;
      align-items: center;
      gap: 16px;
      height: var(--topbar-h);
      padding: 0 24px;
      background: var(--bg-card);
      border-bottom: 1px solid var(--border);
      position: sticky;
      top: 0;
      z-index: 90;
    }
    .topbar-title { flex: 1; min-width: 0; }
    .topbar-title h1 {
      font-size: 16px;
      font-weight: 700;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .topbar-meta {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
    }
    .user-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      height: 32px;
      padding: 0 12px;
      border-radius: var(--radius-full);
      background: var(--bg-muted);
      color: var(--text-secondary);
      font-size: 13px;
      font-weight: 600;
    }
    .user-pill::before {
      content: "";
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--success);
    }
    .sidebar-toggle {
      display: none;
      align-items: center;
      justify-content: center;
      width: 36px;
      height: 36px;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--bg-card);
      color: var(--text-secondary);
      cursor: pointer;
      flex-shrink: 0;
    }

    /* ── Main ── */
    main {
      padding: 20px 24px 40px;
      max-width: 1600px;
      width: 100%;
    }

    /* ── Buttons ── */
    .btn, .button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      height: 36px;
      padding: 0 14px;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--bg-card);
      color: var(--text);
      font: inherit;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
      text-decoration: none;
      transition: all 0.12s ease;
      box-shadow: var(--shadow-xs);
    }
    .btn:hover, .button:hover {
      background: var(--bg-hover);
      border-color: #cbd5e1;
    }
    .btn-primary, .button.primary, .primary-button {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
      box-shadow: 0 1px 2px rgb(37 99 235 / 0.2);
    }
    .btn-primary:hover, .button.primary:hover, .primary-button:hover {
      background: var(--accent-hover);
      border-color: var(--accent-hover);
    }
    .btn-ghost { background: transparent; border-color: transparent; box-shadow: none; }
    .btn-ghost:hover { background: var(--bg-hover); }
    .btn-sm { height: 30px; padding: 0 10px; font-size: 12px; }
    .btn-danger, .danger-button { background: var(--danger); border-color: var(--danger); color: #fff; }
    .btn-danger:hover, .danger-button:hover { background: #b91c1c; }
    .secondary-button { background: var(--bg-card); }

    /* ── Page Header ── */
    .page-header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      margin-bottom: 16px;
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 20px;
      box-shadow: var(--shadow-sm);
    }
    .page-header h2 { margin-bottom: 4px; font-size: 18px; }
    .page-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
    }
    .summary-strip {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }
    .summary-strip span {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border: 1px solid var(--border);
      border-radius: var(--radius-full);
      background: var(--bg-card);
      padding: 5px 10px;
      color: var(--text-secondary);
      font-size: 12px;
      font-weight: 600;
    }
    .summary-strip strong { color: var(--text); }

    /* ── Filters ── */
    .filters {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 10px;
      align-items: end;
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 14px 16px;
      margin-bottom: 16px;
      box-shadow: var(--shadow-xs);
    }
    .filter-panel { background: var(--bg-card); }
    label {
      display: block;
      color: var(--text-muted);
      font-size: 11px;
      font-weight: 600;
      margin-bottom: 4px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    select, input {
      width: 100%;
      height: 36px;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--bg-card);
      color: var(--text);
      padding: 0 10px;
      font: inherit;
      font-size: 13px;
      transition: border-color 0.12s ease, box-shadow 0.12s ease;
    }
    select:focus, input:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-soft);
    }
    select:hover, input:hover { border-color: #cbd5e1; }
    textarea {
      width: 100%;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--bg-card);
      color: var(--text);
      padding: 8px 10px;
      font: inherit;
      font-size: 13px;
      resize: vertical;
    }
    textarea:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-soft);
    }

    /* ── KPI Grid ── */
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .kpi {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 14px 16px;
      box-shadow: var(--shadow-xs);
      position: relative;
      overflow: hidden;
      transition: box-shadow 0.15s ease;
    }
    .kpi:hover { box-shadow: var(--shadow-sm); }
    .kpi::before {
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: 3px;
      background: var(--border);
      border-radius: 0 2px 2px 0;
    }
    .kpi span {
      display: block;
      color: var(--text-muted);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 6px;
    }
    .kpi strong {
      display: block;
      font-size: 22px;
      line-height: 1.2;
      font-weight: 700;
      overflow-wrap: anywhere;
    }
    .kpi.good::before { background: var(--success); }
    .kpi.bad::before { background: var(--danger); }
    .kpi.warn::before { background: var(--warning); }
    .kpi.action::before { background: var(--accent); }
    .kpi.neutral::before { background: var(--accent); }
    .kpi.good strong { color: var(--success); }
    .kpi.bad strong { color: var(--danger); }
    .kpi.warn strong { color: var(--warning); }
    .kpi-card { background: var(--bg-card); }
    .kpi-card .kpi-value { display: block; font-size: 22px; line-height: 1.2; font-weight: 700; color: var(--text); }
    .kpi-card .kpi-label { display: block; color: var(--text-muted); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; margin-top: 4px; }
    .change {
      display: inline-flex;
      align-items: center;
      gap: 3px;
      margin-top: 6px;
      font-size: 12px;
      color: var(--text-muted);
      font-weight: 500;
    }
    .change.up { color: var(--success); }
    .change.down { color: var(--danger); }

    /* ── Premium KPI ── */
    .premium-kpi-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .premium-kpi {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 16px;
      box-shadow: var(--shadow-xs);
      position: relative;
      overflow: hidden;
      transition: box-shadow 0.15s ease;
      min-height: 120px;
    }
    .premium-kpi:hover { box-shadow: var(--shadow-sm); }
    .premium-kpi::before {
      content: "";
      position: absolute;
      inset: 0 0 auto;
      height: 3px;
      background: var(--accent);
    }
    .premium-kpi.good::before { background: var(--success); }
    .premium-kpi.bad::before { background: var(--danger); }
    .premium-kpi.warn::before { background: var(--warning); }
    .premium-kpi.neutral::before { background: var(--text-muted); }
    .premium-kpi span {
      display: block;
      color: var(--text-muted);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 8px;
    }
    .premium-kpi strong {
      display: block;
      color: var(--text);
      font-size: 24px;
      line-height: 1.15;
      font-weight: 700;
      overflow-wrap: anywhere;
    }
    .premium-kpi small {
      display: block;
      margin-top: 8px;
      color: var(--text-secondary);
      font-size: 12px;
      line-height: 1.4;
    }
    .premium-kpi .change {
      display: inline-flex;
      align-items: center;
      border-radius: var(--radius-full);
      padding: 2px 8px;
      background: var(--bg-muted);
      font-weight: 700;
      font-size: 11px;
    }

    /* ── Hero ── */
    .premium-hero {
      position: relative;
      overflow: hidden;
      display: grid;
      grid-template-columns: minmax(0, 1.5fr) minmax(260px, 0.7fr);
      gap: 20px;
      padding: 24px;
      border: 1px solid var(--accent-soft);
      border-radius: var(--radius-xl);
      background: linear-gradient(135deg, #ffffff 0%, #f8fbff 54%, #f0f7ff 100%);
      box-shadow: var(--shadow-sm);
      margin-bottom: 16px;
    }
    .premium-hero::after {
      content: "";
      position: absolute;
      inset: auto -40px -40px auto;
      width: 180px;
      height: 180px;
      border-radius: 50%;
      background: rgb(37 99 235 / 0.06);
      pointer-events: none;
    }
    .hero-content, .hero-panel { position: relative; z-index: 1; }
    .hero-eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 10px;
      padding: 4px 10px;
      border-radius: var(--radius-full);
      background: var(--accent-bg);
      border: 1px solid var(--accent-soft);
      color: var(--accent);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .premium-hero h2 {
      margin: 0 0 8px;
      font-size: 22px;
      line-height: 1.2;
      font-weight: 800;
    }
    .hero-lead {
      max-width: 680px;
      margin: 0;
      color: var(--text-secondary);
      font-size: 14px;
    }
    .hero-panel {
      display: grid;
      gap: 8px;
      align-content: start;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 14px;
      background: rgb(255 255 255 / 0.85);
      box-shadow: var(--shadow-xs);
    }
    .hero-stat {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      padding: 8px 0;
      border-bottom: 1px solid var(--border-light);
      color: var(--text-secondary);
      font-size: 12px;
      font-weight: 600;
    }
    .hero-stat:last-child { border-bottom: 0; }
    .hero-stat strong {
      color: var(--text);
      text-align: right;
      font-size: 13px;
      overflow-wrap: anywhere;
    }

    /* ── Sections / Cards ── */
    .band, .section-card, .table-card, .form-card, .alert-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 20px;
      box-shadow: var(--shadow-xs);
      margin-bottom: 12px;
    }
    .premium-section {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 20px;
      box-shadow: var(--shadow-xs);
      min-width: 0;
    }
    .section-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      margin-bottom: 14px;
    }
    .section-head h2 { margin-bottom: 2px; }

    /* ── Grids ── */
    .premium-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.25fr) minmax(300px, 0.75fr);
      gap: 12px;
      margin-bottom: 12px;
    }
    .dashboard-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 12px;
    }
    .detail-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 12px;
    }
    .analytics-shell { display: grid; gap: 12px; }
    .analytics-control { display: grid; gap: 12px; }
    .analytics-control .filters { margin: 0; }

    /* ── Attention / Events ── */
    .attention-list, .event-list, .shortcut-grid, .marketplace-split {
      display: grid;
      gap: 8px;
    }
    .attention-item {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      align-items: center;
      border: 1px solid var(--border);
      border-left: 3px solid var(--accent);
      border-radius: var(--radius-sm);
      background: var(--bg-muted);
      padding: 12px 14px;
    }
    .attention-item.good { border-left-color: var(--success); }
    .attention-item.bad { border-left-color: var(--danger); }
    .attention-item.warn { border-left-color: var(--warning); }
    .attention-item strong, .event-item strong, .shortcut-card strong {
      display: block;
      color: var(--text);
      margin-bottom: 2px;
      font-size: 13px;
    }
    .attention-item p, .event-item p, .shortcut-card p {
      margin: 0;
      color: var(--text-secondary);
      font-size: 12px;
    }
    .event-item {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--bg-card);
      padding: 10px 12px;
    }
    .event-meta {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      margin-top: 4px;
    }
    .shortcut-grid {
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    }
    .shortcut-card {
      display: block;
      color: inherit;
      text-decoration: none;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--bg-card);
      padding: 12px;
      transition: all 0.12s ease;
    }
    .shortcut-card:hover {
      border-color: var(--accent-soft);
      box-shadow: var(--shadow-sm);
    }

    /* ── Marketplace ── */
    .marketplace-split { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .marketplace-panel {
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: var(--bg-card);
      padding: 14px;
    }
    .marketplace-panel-head {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
      margin-bottom: 10px;
    }
    .marketplace-share {
      color: var(--text-muted);
      font-size: 11px;
      font-weight: 700;
    }
    .mini-stat-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    .mini-stat {
      border-radius: var(--radius-sm);
      background: var(--bg-muted);
      border: 1px solid var(--border-light);
      padding: 8px;
    }
    .mini-stat span {
      display: block;
      color: var(--text-muted);
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 3px;
    }
    .mini-stat strong {
      color: var(--text);
      font-size: 14px;
    }

    /* ── Tables ── */
    .table-wrap {
      width: 100%;
      overflow-x: auto;
      border-radius: var(--radius);
      border: 1px solid var(--border);
      background: var(--bg-card);
    }
    .table {
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      font-size: 13px;
    }
    .table th, .table td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--border-light);
      text-align: left;
      vertical-align: top;
    }
    .table thead {
      background: var(--bg-muted);
      position: sticky;
      top: 0;
      z-index: 5;
    }
    .table th {
      color: var(--text-muted);
      font-weight: 700;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      white-space: nowrap;
      border-bottom: 1px solid var(--border);
    }
    .table tbody tr { transition: background 0.1s ease; }
    .table tbody tr:hover { background: var(--bg-hover); }
    .table tbody tr:last-child td { border-bottom: 0; }
    .table td.num, .table th.num { text-align: right; }
    .table a {
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
    }
    .table a:hover { color: var(--accent-hover); text-decoration: underline; }

    /* ── Badges ── */
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      border-radius: var(--radius-full);
      padding: 2px 8px;
      background: var(--bg-muted);
      color: var(--text-muted);
      font-size: 11px;
      font-weight: 700;
      white-space: nowrap;
      border: 1px solid transparent;
    }
    .badge.good { background: var(--success-soft); color: #047857; border-color: var(--success-border); }
    .badge.bad { background: var(--danger-soft); color: #b91c1c; border-color: var(--danger-border); }
    .badge.warn { background: var(--warning-soft); color: #92400e; border-color: var(--warning-border); }
    .badge.action { background: var(--accent-soft); color: var(--accent); border-color: var(--ozon-border); }
    .badge.wb { background: var(--wb-soft); color: var(--wb); border-color: var(--wb-border); }
    .badge.ozon { background: var(--ozon-soft); color: var(--ozon); border-color: var(--ozon-border); }
    .marketplace-badge {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      min-height: 24px;
      border-radius: var(--radius-full);
      padding: 2px 8px;
      font-size: 11px;
      font-weight: 700;
      white-space: nowrap;
      border: 1px solid transparent;
    }
    .mp-logo {
      display: inline-grid;
      place-items: center;
      width: 18px;
      height: 18px;
      border-radius: 4px;
      color: #fff;
      font-size: 9px;
      font-weight: 900;
      line-height: 1;
    }
    .marketplace-badge.wb .mp-logo { background: var(--wb); }
    .marketplace-badge.ozon .mp-logo { background: var(--ozon); }
    .marketplace-badge.wb { background: var(--wb-soft); color: #6d28d9; border-color: var(--wb-border); }
    .marketplace-badge.ozon { background: var(--ozon-soft); color: #1d4ed8; border-color: var(--ozon-border); }
    .marketplace-badge.neutral { background: var(--bg-muted); color: #334155; border-color: var(--border); }

    /* ── Charts ── */
    .chart svg { width: 100%; height: auto; display: block; }
    .chart-empty {
      min-height: 180px;
      display: grid;
      place-items: center;
      color: var(--text-muted);
      background: var(--bg-muted);
      border: 1px dashed var(--border);
      border-radius: var(--radius);
      font-weight: 500;
      font-size: 13px;
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      margin-top: 10px;
      color: var(--text-muted);
      font-size: 12px;
      font-weight: 500;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      display: inline-block;
      margin-right: 5px;
    }

    /* ── Progress ── */
    .progress-grid { display: grid; grid-template-columns: repeat(3, minmax(140px, 1fr)); gap: 10px; margin-bottom: 12px; }
    .progress-card { border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 10px; background: var(--bg-muted); }
    .progress-card div:first-child { display: flex; justify-content: space-between; gap: 8px; align-items: center; font-size: 12px; }
    .progress-track { height: 6px; border-radius: var(--radius-full); background: var(--border); overflow: hidden; margin: 8px 0 4px; }
    .progress-track span { display: block; height: 100%; background: var(--accent); border-radius: var(--radius-full); transition: width 0.3s ease; }

    /* ── Misc ── */
    .status-chip, .pill {
      display: inline-flex;
      align-items: center;
      border-radius: var(--radius-full);
      padding: 3px 10px;
      background: var(--bg-muted);
      border: 1px solid var(--border);
      font-size: 12px;
      font-weight: 700;
    }
    .metric-delta { color: var(--text-muted); font-size: 12px; font-weight: 600; }
    .tabs, .breadcrumbs {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 12px;
    }
    .product-thumb {
      width: 44px;
      height: 44px;
      display: grid;
      place-items: center;
      border-radius: var(--radius-sm);
      background: var(--bg-muted);
      color: var(--text-muted);
      font-size: 10px;
      text-align: center;
      flex-shrink: 0;
      border: 1px solid var(--border);
    }
    .subnav {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 16px;
    }
    .subnav a {
      color: var(--text-secondary);
      text-decoration: none;
      border: 1px solid var(--border);
      background: var(--bg-card);
      border-radius: var(--radius-full);
      padding: 6px 12px;
      font-size: 12px;
      font-weight: 600;
      transition: all 0.12s ease;
    }
    .subnav a:hover {
      background: var(--bg-hover);
      border-color: #cbd5e1;
    }
    .subnav a.active {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }
    .kv {
      display: grid;
      grid-template-columns: minmax(120px, 180px) minmax(0, 1fr);
      gap: 8px 14px;
      font-size: 13px;
    }
    .kv span { color: var(--text-secondary); font-weight: 500; }
    .kv strong { font-weight: 600; }
    .mono {
      font-family: var(--font-mono);
      font-size: 12px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      background: var(--bg-muted);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 14px;
      line-height: 1.5;
    }
    .wide { grid-column: 1 / -1; }
    .empty-state {
      min-height: 140px;
      display: grid;
      place-items: center;
      text-align: center;
      color: var(--text-muted);
      background: var(--bg-muted);
      border: 1px dashed var(--border);
      border-radius: var(--radius);
      padding: 20px;
      font-weight: 600;
      font-size: 13px;
    }

    /* ── Locked Feature ── */
    .locked-feature {
      text-align: center;
      padding: 48px 24px;
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
    }
    .locked-feature h2 { font-size: 20px; margin-bottom: 8px; }
    .locked-feature p { color: var(--text-secondary); max-width: 420px; margin: 0 auto 16px; }
    .locked-feature ul { list-style: none; padding: 0; margin: 0 0 20px; }
    .locked-feature li { padding: 6px 0; color: var(--text-secondary); font-size: 13px; }
    .locked-feature li::before { content: "✓ "; color: var(--success); font-weight: 700; }

    /* ── Error State ── */
    .error-state {
      text-align: center;
      padding: 40px 24px;
      background: var(--bg-card);
      border: 1px solid var(--danger-border);
      border-radius: var(--radius-lg);
    }
    .error-state h2 { color: var(--danger); }
    .error-state p { color: var(--text-secondary); max-width: 420px; margin: 0 auto 16px; }

    /* ── Responsive ── */
    @media (max-width: 1200px) {
      .shell { grid-template-columns: 220px minmax(0, 1fr); }
      .premium-kpi-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .premium-grid { grid-template-columns: 1fr; }
      .dashboard-grid { grid-template-columns: 1fr; }
      .detail-grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 900px) {
      .shell { grid-template-columns: 1fr; }
      aside {
        position: fixed;
        left: -280px;
        top: 0;
        width: 260px;
        height: 100vh;
        z-index: 200;
        transition: left 0.2s ease;
        box-shadow: var(--shadow-lg);
      }
      aside.is-open { left: 0; }
      .sidebar-toggle { display: inline-flex; }
      main { padding: 16px; }
      .topbar { padding: 0 16px; }
      .filters { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
      .kpi-grid { grid-template-columns: repeat(2, minmax(140px, 1fr)); }
      .premium-kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .premium-hero { grid-template-columns: 1fr; }
      .shortcut-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .marketplace-split { grid-template-columns: 1fr; }
    }
    @media (max-width: 560px) {
      .kpi-grid { grid-template-columns: 1fr; }
      .premium-kpi-grid { grid-template-columns: 1fr; }
      .mini-stat-grid { grid-template-columns: 1fr; }
      .shortcut-grid { grid-template-columns: 1fr; }
      .filters { grid-template-columns: 1fr; }
      .premium-hero h2 { font-size: 18px; }
      .premium-hero, .premium-section, .band { padding: 14px; }
      .topbar-title h1 { font-size: 14px; }
    }
    """


def _js() -> str:
    return """
    (function() {
      var toggle = document.querySelector('.sidebar-toggle');
      var sidebar = document.getElementById('sidebar');
      if (toggle && sidebar) {
        toggle.addEventListener('click', function() {
          sidebar.classList.toggle('is-open');
        });
      }
      document.addEventListener('click', function(e) {
        if (sidebar && sidebar.classList.contains('is-open') && !sidebar.contains(e.target) && !e.target.closest('.sidebar-toggle')) {
          sidebar.classList.remove('is-open');
        }
      });
      document.querySelectorAll('.table-wrap').forEach(function(wrap) {
        var table = wrap.querySelector('table');
        if (table && table.scrollWidth > wrap.clientWidth) {
          wrap.style.position = 'relative';
        }
      });
    })();
    """


def _nav(active_path: str) -> str:
    groups = []
    for title, items in NAV_GROUPS:
        links = []
        for label, href in items:
            active = ' class="active"' if href == active_path else ""
            icon_svg = NAV_ICONS.get(label, NAV_ICONS_FALLBACK)
            links.append(
                f'<a{active} href="{href}"><span class="nav-icon">{icon_svg}</span>'
                f"<span>{escape(label)}</span></a>"
            )
        groups.append(
            '<div class="nav-group">'
            f'<div class="nav-title">{escape(title)}</div>' + "\n".join(links) + "</div>"
        )
    return "\n".join(groups)
