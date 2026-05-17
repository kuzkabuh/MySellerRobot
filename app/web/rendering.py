"""version: 3.0.0
description: Server-side HTML rendering helpers and Material-style web cabinet shell.
updated: 2026-05-17
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
        ],
    ),
]


def page(title: str, user_name: str, content: str, *, active_path: str = "/web/") -> str:
    safe_title = escape(title)
    safe_user = escape(user_name or "селлер")
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title} — KUZ’KA.SELLER</title>
  <style>
    :root {{
      color-scheme: light;
      --primary: #4557f6;
      --primary-hover: #3543d8;
      --primary-soft: #eef0ff;
      --color-primary: #4557f6;
      --color-primary-hover: #3543d8;
      --color-secondary: #006d77;
      --color-background: #f8fafc;
      --color-surface: #ffffff;
      --color-surface-muted: #f9fafb;
      --color-border: #e2e8f0;
      --color-text-primary: #0f172a;
      --color-text-secondary: #475569;
      --color-success: #10b981;
      --color-warning: #f59e0b;
      --color-danger: #ef4444;
      --color-info: #0ea5e9;
      --space-1: 4px;
      --space-2: 8px;
      --space-3: 12px;
      --space-4: 16px;
      --space-5: 20px;
      --space-6: 24px;
      --secondary: #006d77;
      --surface: #ffffff;
      --surface-alt: #f9fafb;
      --background: #f8fafc;
      --text-primary: #0f172a;
      --text-secondary: #475569;
      --border: #e2e8f0;
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
      --info: #0ea5e9;
      --bg: #f8fafc;
      --panel: #ffffff;
      --panel-soft: #f9fafb;
      --text: #0f172a;
      --text-secondary: #475569;
      --muted: #64748b;
      --line: #e2e8f0;
      --sidebar: #1e293b;
      --sidebar-active: #334155;
      --sidebar-hover: #2d3a4f;
      --accent: #0ea5e9;
      --accent-hover: #0284c7;
      --accent-soft: #e0f2fe;
      --wb: #8b5cf6;
      --ozon: #3b82f6;
      --good: #10b981;
      --good-soft: #d1fae5;
      --bad: #ef4444;
      --bad-soft: #fee2e2;
      --warn: #f59e0b;
      --warn-soft: #fef3c7;
      --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
      --shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1);
      --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
      --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1);
      --radius: 10px;
      --radius-sm: 6px;
      --radius-lg: 14px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family:
        -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', 'Roboto',
        'Helvetica Neue', Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }}
    .shell {{
      display: grid;
      grid-template-columns: 260px minmax(0, 1fr);
      min-height: 100vh;
    }}
    aside {{
      background: var(--sidebar);
      color: white;
      padding: 28px 20px;
      box-shadow: var(--shadow-lg);
      position: sticky;
      top: 0;
      height: 100vh;
      overflow-y: auto;
    }}
    .brand {{
      font-size: 20px;
      font-weight: 700;
      margin-bottom: 32px;
      letter-spacing: -0.02em;
      background: linear-gradient(135deg, #60a5fa 0%, #a78bfa 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }}
    nav a {{
      display: flex;
      align-items: center;
      color: #cbd5e1;
      text-decoration: none;
      padding: 11px 14px;
      border-radius: var(--radius-sm);
      margin-bottom: 4px;
      font-size: 14px;
      font-weight: 500;
      transition: all 0.15s ease;
    }}
    nav a:hover {{
      background: var(--sidebar-hover);
      color: #fff;
      transform: translateX(2px);
    }}
    nav a.active {{
      background: var(--sidebar-active);
      color: #fff;
      box-shadow: var(--shadow-sm);
    }}
    .nav-group {{
      margin-top: 18px;
    }}
    .nav-group:first-child {{ margin-top: 0; }}
    .nav-title {{
      color: #94a3b8;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      padding: 0 14px 8px;
    }}
    main {{
      padding: 32px;
      max-width: 1600px;
    }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: center;
      margin-bottom: 28px;
    }}
    .page-header {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: flex-start;
      margin-bottom: 20px;
      background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      padding: 24px;
      box-shadow: var(--shadow-sm);
    }}
    .page-header h2 {{
      margin-bottom: 6px;
      font-size: 24px;
    }}
    .page-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      justify-content: flex-end;
    }}
    h1 {{
      font-size: 28px;
      margin: 0;
      letter-spacing: -0.02em;
      font-weight: 700;
      color: var(--text);
    }}
    h2 {{
      font-size: 20px;
      margin: 0 0 16px;
      letter-spacing: -0.01em;
      font-weight: 600;
      color: var(--text);
    }}
    h3 {{
      font-size: 16px;
      margin: 0 0 12px;
      letter-spacing: -0.01em;
      font-weight: 600;
    }}
    .muted {{
      color: var(--muted);
      font-size: 14px;
    }}
    .filters {{
      display: grid;
      grid-template-columns: repeat(5, minmax(140px, 1fr)) auto;
      gap: 12px;
      align-items: end;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 20px;
      margin-bottom: 20px;
      box-shadow: var(--shadow-sm);
    }}
    .filter-panel {{ background: var(--panel); }}
    label {{
      display: block;
      color: var(--text-secondary);
      font-size: 13px;
      font-weight: 500;
      margin-bottom: 6px;
    }}
    select, input {{
      width: 100%;
      height: 40px;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      background: white;
      color: var(--text);
      padding: 0 12px;
      font: inherit;
      font-size: 14px;
      transition: all 0.15s ease;
    }}
    select:focus, input:focus {{
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-soft);
    }}
    select:hover, input:hover {{
      border-color: var(--muted);
    }}
    .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 40px;
      border: 1px solid var(--line);
      color: var(--text);
      text-decoration: none;
      border-radius: var(--radius-sm);
      padding: 10px 16px;
      background: white;
      cursor: pointer;
      font: inherit;
      font-size: 14px;
      font-weight: 500;
      white-space: nowrap;
      transition: all 0.15s ease;
      box-shadow: var(--shadow-sm);
    }}
    .button:hover {{
      background: var(--panel-soft);
      border-color: var(--muted);
      transform: translateY(-1px);
      box-shadow: var(--shadow);
    }}
    .button.primary {{
      background: var(--accent);
      border-color: var(--accent);
      color: white;
    }}
    .primary-button {{ background: var(--accent); border-color: var(--accent); color: white; }}
    .secondary-button {{ background: white; }}
    .danger-button {{ background: var(--bad); border-color: var(--bad); color: white; }}
    .button.primary:hover {{
      background: var(--accent-hover);
      border-color: var(--accent-hover);
    }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
    }}
    .kpi {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 20px;
      min-height: 120px;
      box-shadow: var(--shadow-sm);
      transition: all 0.2s ease;
    }}
    .kpi-card {{ background: var(--panel); }}
    .kpi:hover {{
      box-shadow: var(--shadow-md);
      transform: translateY(-2px);
    }}
    .kpi span {{
      display: block;
      color: var(--muted);
      font-size: 13px;
      font-weight: 500;
      margin-bottom: 10px;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }}
    .kpi strong {{
      display: block;
      font-size: 26px;
      line-height: 1.2;
      overflow-wrap: anywhere;
      font-weight: 700;
    }}
    .change {{
      display: inline-block;
      margin-top: 10px;
      font-size: 13px;
      color: var(--muted);
      font-weight: 500;
    }}
    .change.up {{ color: var(--good); }}
    .change.down {{ color: var(--bad); }}
    .kpi.good strong {{ color: var(--good); }}
    .kpi.bad strong {{ color: var(--bad); }}
    .kpi.warn strong {{ color: var(--warn); }}
    .dashboard-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 20px;
      margin-top: 20px;
    }}
    .band {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 24px;
      min-width: 0;
      box-shadow: var(--shadow-sm);
      transition: box-shadow 0.2s ease;
    }}
    .section-card, .table-card, .form-card, .alert-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 24px;
      box-shadow: var(--shadow-sm);
    }}
    .empty-state {{
      min-height: 160px;
      display: grid;
      place-items: center;
      text-align: center;
      color: var(--muted);
      background: var(--panel-soft);
      border: 2px dashed var(--line);
      border-radius: var(--radius);
      padding: 24px;
    }}
    .band:hover {{
      box-shadow: var(--shadow);
    }}
    .wide {{ grid-column: 1 / -1; }}
    .chart svg {{ width: 100%; height: auto; display: block; }}
    .chart-empty {{
      min-height: 200px;
      display: grid;
      place-items: center;
      color: var(--muted);
      background: var(--panel-soft);
      border: 2px dashed var(--line);
      border-radius: var(--radius);
      font-weight: 500;
    }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      margin-top: 14px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 500;
    }}
    .dot {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      display: inline-block;
      margin-right: 6px;
    }}
    .table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    .table-wrap {{
      width: 100%;
      overflow-x: auto;
      border-radius: var(--radius-sm);
    }}
    .table th, .table td {{
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    .table thead {{
      background: var(--panel-soft);
    }}
    .table th {{
      color: var(--text-secondary);
      font-weight: 600;
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }}
    .table tbody tr {{
      transition: background 0.15s ease;
    }}
    .table tbody tr:hover {{
      background: var(--panel-soft);
    }}
    .table td.num, .table th.num {{ text-align: right; }}
    .table a {{
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
      transition: color 0.15s ease;
    }}
    .table a:hover {{
      color: var(--accent-hover);
      text-decoration: underline;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      border-radius: 999px;
      padding: 4px 10px;
      background: var(--panel-soft);
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
      white-space: nowrap;
    }}
    .badge.good {{ background: var(--good-soft); color: var(--good); }}
    .badge.bad {{ background: var(--bad-soft); color: var(--bad); }}
    .badge.warn {{ background: var(--warn-soft); color: var(--warn); }}
    .badge.action {{ background: var(--accent-soft); color: var(--accent); }}
    .badge.wb {{ background: #f3e8ff; color: var(--wb); }}
    .badge.ozon {{ background: #dbeafe; color: var(--ozon); }}
    .marketplace-badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 26px;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
      border: 1px solid transparent;
    }}
    .marketplace-badge.wb::before {{ content: "WB"; }}
    .marketplace-badge.ozon::before {{ content: "O"; }}
    .marketplace-badge.wb {{ background:#f3e8ff;color:#6d28d9;border-color:#ddd6fe; }}
    .marketplace-badge.ozon {{ background:#dbeafe;color:#1d4ed8;border-color:#bfdbfe; }}
    .marketplace-badge.neutral {{ background:#f1f5f9;color:#334155;border-color:#e2e8f0; }}
    .progress-grid {{ display:grid;grid-template-columns:repeat(3,minmax(160px,1fr));gap:12px;margin-bottom:14px; }}
    .progress-card {{ border:1px solid var(--line);border-radius:var(--radius-sm);padding:12px;background:var(--panel-soft); }}
    .progress-card div:first-child {{ display:flex;justify-content:space-between;gap:10px;align-items:center; }}
    .progress-track {{ height:8px;border-radius:999px;background:#e2e8f0;overflow:hidden;margin:10px 0 6px; }}
    .progress-track span {{ display:block;height:100%;background:var(--primary);border-radius:999px; }}
    .status-chip, .pill {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 4px 10px;
      background: var(--panel-soft);
      border: 1px solid var(--line);
      font-size: 12px;
      font-weight: 700;
    }}
    .metric-delta {{ color: var(--muted); font-size: 13px; font-weight: 600; }}
    .tabs, .breadcrumbs {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 16px;
    }}
    .product-thumb {{
      width: 48px;
      height: 48px;
      display: grid;
      place-items: center;
      border-radius: var(--radius-sm);
      background: var(--panel-soft);
      color: var(--muted);
      font-size: 11px;
      text-align: center;
      flex: 0 0 auto;
      border: 1px solid var(--line);
    }}
    .subnav {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 20px;
    }}
    .subnav a {{
      color: var(--text);
      text-decoration: none;
      border: 1px solid var(--line);
      background: white;
      border-radius: var(--radius-sm);
      padding: 10px 14px;
      font-size: 14px;
      font-weight: 500;
      transition: all 0.15s ease;
      box-shadow: var(--shadow-sm);
    }}
    .subnav a:hover {{
      background: var(--panel-soft);
      transform: translateY(-1px);
      box-shadow: var(--shadow);
    }}
    .subnav a.active {{
      background: var(--accent);
      border-color: var(--accent);
      color: white;
      box-shadow: var(--shadow);
    }}
    .detail-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 20px;
      margin-top: 20px;
    }}
    .kv {{
      display: grid;
      grid-template-columns: minmax(130px, 200px) minmax(0, 1fr);
      gap: 10px 16px;
      font-size: 14px;
    }}
    .kv span {{
      color: var(--text-secondary);
      font-weight: 500;
    }}
    .kv strong {{
      font-weight: 600;
    }}
    .mono {{
      font-family:
        ui-monospace, 'SF Mono', 'Cascadia Code', 'Source Code Pro',
        Menlo, Consolas, monospace;
      font-size: 12px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      background: var(--panel-soft);
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      padding: 16px;
      line-height: 1.5;
    }}
    @media (max-width: 1100px) {{
      .filters {{ grid-template-columns: repeat(3, minmax(130px, 1fr)); }}
      .kpi-grid {{ grid-template-columns: repeat(2, minmax(160px, 1fr)); }}
      .dashboard-grid {{ grid-template-columns: 1fr; }}
      .detail-grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 760px) {{
      .shell {{ grid-template-columns: 1fr; }}
      aside {{
        position: static;
        height: auto;
      }}
      main {{ padding: 20px; }}
      .filters {{ grid-template-columns: 1fr; }}
      .topbar {{
        align-items: flex-start;
        flex-direction: column;
      }}
      .page-header {{
        flex-direction: column;
      }}
    }}
    @media (max-width: 520px) {{
      .kpi-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <div class="brand">KUZ’KA.SELLER</div>
      <nav>
        {_nav(active_path)}
      </nav>
    </aside>
    <main>
      <div class="topbar">
        <div>
          <h1>{safe_title}</h1>
          <div class="muted">Вошли как {safe_user}</div>
        </div>
        <a class="button" href="/web/logout">Выйти</a>
      </div>
      {content}
    </main>
  </div>
</body>
</html>"""


def _nav(active_path: str) -> str:
    groups = []
    for title, items in NAV_GROUPS:
        links = []
        for label, href in items:
            active = ' class="active"' if href == active_path else ""
            links.append(f'<a{active} href="{href}">{escape(label)}</a>')
        groups.append(
            '<div class="nav-group">'
            f'<div class="nav-title">{escape(title)}</div>' + "\n".join(links) + "</div>"
        )
    return "\n".join(groups)
