"""version: 2.4.0
description: Server-side HTML rendering helpers for the web cabinet.
updated: 2026-05-15
"""

from html import escape

NAV_ITEMS = [
    ("Главная", "/web/"),
    ("Заказы", "/web/orders"),
    ("Прибыль", "/web/profit"),
    ("План/факт", "/web/plan-fact"),
    ("Продажи", "/web/sales"),
    ("Возвраты", "/web/returns"),
    ("Товары", "/web/products"),
    ("Остатки", "/web/stocks"),
    ("Аналитика", "/web/analytics"),
    ("Контроль", "/web/control"),
    ("Себестоимость", "/web/costs"),
    ("Настройки", "/web/settings"),
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
      --bg: #f5f7fb;
      --panel: #ffffff;
      --panel-soft: #f9fbfd;
      --text: #202632;
      --muted: #667085;
      --line: #d9e0e8;
      --sidebar: #172033;
      --sidebar-active: #2b3a55;
      --accent: #0f6f8f;
      --accent-soft: #e3f3f7;
      --wb: #7b3fc5;
      --ozon: #1267d6;
      --good: #147d4a;
      --bad: #b42318;
      --warn: #a65f00;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    .shell {{
      display: grid;
      grid-template-columns: 248px minmax(0, 1fr);
      min-height: 100vh;
    }}
    aside {{
      background: var(--sidebar);
      color: white;
      padding: 22px 16px;
    }}
    .brand {{
      font-size: 18px;
      font-weight: 700;
      margin-bottom: 24px;
      letter-spacing: 0;
    }}
    nav a {{
      display: block;
      color: #d8dee8;
      text-decoration: none;
      padding: 10px 12px;
      border-radius: 6px;
      margin-bottom: 4px;
      font-size: 14px;
    }}
    nav a.active, nav a:hover {{ background: var(--sidebar-active); color: #fff; }}
    main {{ padding: 24px; }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      margin-bottom: 18px;
    }}
    h1 {{ font-size: 24px; margin: 0; letter-spacing: 0; }}
    h2 {{ font-size: 18px; margin: 0 0 12px; letter-spacing: 0; }}
    h3 {{ font-size: 15px; margin: 0 0 10px; letter-spacing: 0; }}
    .muted {{ color: var(--muted); }}
    .filters {{
      display: grid;
      grid-template-columns: repeat(5, minmax(130px, 1fr)) auto;
      gap: 10px;
      align-items: end;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      margin-bottom: 14px;
    }}
    label {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 5px; }}
    select, input {{
      width: 100%;
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: white;
      color: var(--text);
      padding: 0 10px;
      font: inherit;
      font-size: 14px;
    }}
    .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 38px;
      border: 1px solid var(--line);
      color: var(--text);
      text-decoration: none;
      border-radius: 6px;
      padding: 9px 12px;
      background: white;
      cursor: pointer;
      font: inherit;
      white-space: nowrap;
    }}
    .button.primary {{ background: var(--accent); border-color: var(--accent); color: white; }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(160px, 1fr));
      gap: 12px;
    }}
    .kpi {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 15px;
      min-height: 112px;
    }}
    .kpi span {{ display: block; color: var(--muted); font-size: 13px; margin-bottom: 8px; }}
    .kpi strong {{ display: block; font-size: 22px; line-height: 1.2; overflow-wrap: anywhere; }}
    .change {{ display: inline-block; margin-top: 9px; font-size: 12px; color: var(--muted); }}
    .change.up {{ color: var(--good); }}
    .change.down {{ color: var(--bad); }}
    .kpi.good strong {{ color: var(--good); }}
    .kpi.bad strong {{ color: var(--bad); }}
    .dashboard-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-top: 14px;
    }}
    .band {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      min-width: 0;
    }}
    .wide {{ grid-column: 1 / -1; }}
    .chart svg {{ width: 100%; height: auto; display: block; }}
    .chart-empty {{
      min-height: 190px;
      display: grid;
      place-items: center;
      color: var(--muted);
      background: var(--panel-soft);
      border: 1px dashed var(--line);
      border-radius: 8px;
    }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 10px;
      color: var(--muted);
      font-size: 13px;
    }}
    .dot {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      display: inline-block;
      margin-right: 5px;
    }}
    .table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    .table-wrap {{
      width: 100%;
      overflow-x: auto;
    }}
    .table th, .table td {{
      padding: 10px 8px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    .table th {{ color: var(--muted); font-weight: 600; }}
    .table td.num, .table th.num {{ text-align: right; }}
    .table a {{ color: var(--accent); text-decoration: none; font-weight: 600; }}
    .badge {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      border-radius: 999px;
      padding: 3px 8px;
      background: var(--panel-soft);
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }}
    .badge.good {{ background: #e6f4ec; color: var(--good); }}
    .badge.bad {{ background: #fde8e5; color: var(--bad); }}
    .badge.warn {{ background: #fff3da; color: var(--warn); }}
    .badge.action {{ background: var(--accent-soft); color: var(--accent); }}
    .badge.wb {{ background: #f1e8fb; color: var(--wb); }}
    .badge.ozon {{ background: #e9f1ff; color: var(--ozon); }}
    .product-thumb {{
      width: 48px;
      height: 48px;
      display: grid;
      place-items: center;
      border-radius: 6px;
      background: var(--panel-soft);
      color: var(--muted);
      font-size: 11px;
      text-align: center;
      flex: 0 0 auto;
    }}
    .subnav {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 14px;
    }}
    .subnav a {{
      color: var(--text);
      text-decoration: none;
      border: 1px solid var(--line);
      background: white;
      border-radius: 6px;
      padding: 8px 10px;
      font-size: 14px;
    }}
    .subnav a.active {{ background: var(--accent); border-color: var(--accent); color: white; }}
    .detail-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-top: 14px;
    }}
    .kv {{
      display: grid;
      grid-template-columns: minmax(120px, 180px) minmax(0, 1fr);
      gap: 8px 12px;
      font-size: 14px;
    }}
    .kv span {{ color: var(--muted); }}
    .mono {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      background: var(--panel-soft);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
    }}
    @media (max-width: 1100px) {{
      .filters {{ grid-template-columns: repeat(3, minmax(130px, 1fr)); }}
      .kpi-grid {{ grid-template-columns: repeat(2, minmax(140px, 1fr)); }}
      .dashboard-grid {{ grid-template-columns: 1fr; }}
      .detail-grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 760px) {{
      .shell {{ grid-template-columns: 1fr; }}
      aside {{ position: static; }}
      main {{ padding: 16px; }}
      .filters {{ grid-template-columns: 1fr; }}
      .topbar {{ align-items: flex-start; flex-direction: column; }}
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
    links = []
    for label, href in NAV_ITEMS:
        active = ' class="active"' if href == active_path else ""
        links.append(f'<a{active} href="{href}">{escape(label)}</a>')
    return "\n".join(links)
