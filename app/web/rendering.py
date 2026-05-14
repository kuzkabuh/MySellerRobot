"""version: 1.0.0
description: Minimal server-side HTML rendering helpers for the web cabinet.
updated: 2026-05-14
"""

from html import escape


def page(title: str, user_name: str, content: str) -> str:
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
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #1f2933;
      --muted: #687382;
      --line: #dde3ea;
      --accent: #146c94;
      --good: #147d4a;
      --bad: #b42318;
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
      background: #111827;
      color: white;
      padding: 22px 16px;
    }}
    .brand {{
      font-size: 18px;
      font-weight: 700;
      margin-bottom: 24px;
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
    nav a.active, nav a:hover {{ background: #243044; color: #fff; }}
    main {{ padding: 24px; }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      margin-bottom: 22px;
    }}
    h1 {{ font-size: 24px; margin: 0; }}
    .muted {{ color: var(--muted); }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(160px, 1fr));
      gap: 12px;
    }}
    .kpi {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .kpi span {{ display: block; color: var(--muted); font-size: 13px; margin-bottom: 8px; }}
    .kpi strong {{ font-size: 22px; }}
    .band {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      margin-top: 16px;
      padding: 18px;
    }}
    .button {{
      display: inline-block;
      border: 1px solid var(--line);
      color: var(--text);
      text-decoration: none;
      border-radius: 6px;
      padding: 9px 12px;
      background: white;
    }}
    @media (max-width: 860px) {{
      .shell {{ grid-template-columns: 1fr; }}
      aside {{ position: static; }}
      .kpi-grid {{ grid-template-columns: repeat(2, minmax(140px, 1fr)); }}
    }}
    @media (max-width: 520px) {{
      main {{ padding: 16px; }}
      .kpi-grid {{ grid-template-columns: 1fr; }}
      .topbar {{ align-items: flex-start; flex-direction: column; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <div class="brand">KUZ’KA.SELLER</div>
      <nav>
        <a class="active" href="/web/">Главная</a>
        <a href="/web/orders">Заказы</a>
        <a href="/web/profit">Прибыль</a>
        <a href="/web/products">Товары</a>
        <a href="/web/stocks">Остатки</a>
        <a href="/web/analytics">Аналитика</a>
        <a href="/web/control">Контроль</a>
        <a href="/web/costs">Себестоимость</a>
        <a href="/web/settings">Настройки</a>
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
