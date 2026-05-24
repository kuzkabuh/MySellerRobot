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
        ],
    ),
]

NAV_ICONS = {
    "Главная": "Об",
    "Заказы": "Зк",
    "Продажи": "Пр",
    "Возвраты": "Вз",
    "Прибыль": "₽",
    "План/факт": "%",
    "Безубыточность": "0",
    "Себестоимость": "Сб",
    "МРЦ WB": "МР",
    "Цены и акции": "ЦА",
    "Товары": "Тв",
    "Сопоставление WB / Ozon": "↔",
    "Остатки": "Ос",
    "Алерты": "Ал",
    "Качество данных": "Кд",
    "Контроль ошибок": "!",
    "Аналитика": "Ан",
    "Кабинеты МП": "МП",
    "Подписка и тариф": "Тф",
    "Профиль и настройки": "Пф",
    "Настройки": "Нс",
    "Комиссии МП (admin)": "Км",
}


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
      --primary: #2563eb;
      --primary-hover: #1d4ed8;
      --primary-soft: #eff6ff;
      --color-primary: #2563eb;
      --color-primary-hover: #1d4ed8;
      --color-secondary: #0f766e;
      --color-background: #f3f6fb;
      --color-surface: #ffffff;
      --color-surface-muted: #f8fafc;
      --color-border: #dbe3ef;
      --color-text-primary: #0f172a;
      --color-text-secondary: #475569;
      --color-success: #059669;
      --color-warning: #d97706;
      --color-danger: #dc2626;
      --color-info: #2563eb;
      --space-1: 4px;
      --space-2: 8px;
      --space-3: 12px;
      --space-4: 16px;
      --space-5: 20px;
      --space-6: 24px;
      --secondary: #0f766e;
      --surface: #ffffff;
      --surface-alt: #f8fafc;
      --background: #f3f6fb;
      --text-primary: #0f172a;
      --text-secondary: #475569;
      --border: #dbe3ef;
      --success: #059669;
      --warning: #d97706;
      --danger: #dc2626;
      --info: #2563eb;
      --bg: #f3f6fb;
      --panel: #ffffff;
      --panel-soft: #f8fafc;
      --text: #0f172a;
      --text-secondary: #475569;
      --muted: #64748b;
      --line: #dbe3ef;
      --sidebar: #ffffff;
      --sidebar-active: #eff6ff;
      --sidebar-hover: #f8fafc;
      --accent: #2563eb;
      --accent-hover: #1d4ed8;
      --accent-soft: #dbeafe;
      --wb: #7c3aed;
      --ozon: #2563eb;
      --good: #059669;
      --good-soft: #dcfce7;
      --bad: #dc2626;
      --bad-soft: #fee2e2;
      --warn: #d97706;
      --warn-soft: #fef3c7;
      --neutral-soft: #f1f5f9;
      --shadow-sm: 0 1px 2px 0 rgb(15 23 42 / 0.05);
      --shadow: 0 10px 30px -24px rgb(15 23 42 / 0.45);
      --shadow-md: 0 18px 45px -32px rgb(15 23 42 / 0.55);
      --shadow-lg: 0 24px 70px -42px rgb(15 23 42 / 0.58);
      --radius: 12px;
      --radius-sm: 8px;
      --radius-lg: 18px;
      --radius-xl: 24px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family:
        -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', 'Roboto',
        'Helvetica Neue', Arial, sans-serif;
      background:
        radial-gradient(circle at 18% -8%, rgb(37 99 235 / 0.10), transparent 28%),
        linear-gradient(180deg, #f8fbff 0%, var(--bg) 42%);
      color: var(--text);
      line-height: 1.55;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }}
    .shell {{
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
      min-height: 100vh;
    }}
    aside {{
      background: var(--sidebar);
      color: var(--text);
      padding: 22px 18px;
      border-right: 1px solid var(--line);
      position: sticky;
      top: 0;
      height: 100vh;
      overflow-y: auto;
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 18px;
      font-weight: 800;
      margin-bottom: 22px;
      letter-spacing: 0;
      color: var(--text);
    }}
    .brand::before {{
      content: "MP";
      display: inline-grid;
      place-items: center;
      width: 38px;
      height: 38px;
      border-radius: 12px;
      background: linear-gradient(135deg, #2563eb, #0f766e);
      color: white;
      font-size: 12px;
      letter-spacing: 0.04em;
      box-shadow: var(--shadow-md);
    }}
    nav a {{
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--text-secondary);
      text-decoration: none;
      padding: 9px 10px;
      border-radius: 10px;
      margin-bottom: 3px;
      font-size: 14px;
      font-weight: 650;
      border: 1px solid transparent;
      transition: all 0.15s ease;
    }}
    nav a:hover {{
      background: var(--sidebar-hover);
      color: var(--text);
      border-color: var(--line);
    }}
    nav a.active {{
      background: var(--sidebar-active);
      color: var(--accent);
      border-color: #bfdbfe;
      box-shadow: none;
    }}
    .nav-icon {{
      display: inline-grid;
      place-items: center;
      width: 26px;
      height: 26px;
      flex: 0 0 auto;
      border-radius: 8px;
      background: var(--neutral-soft);
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
    }}
    nav a.active .nav-icon {{
      background: var(--accent);
      color: white;
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
      padding: 0 10px 8px;
    }}
    main {{
      padding: 26px 30px 38px;
      max-width: 1680px;
      width: 100%;
    }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: center;
      margin-bottom: 22px;
      background: rgb(255 255 255 / 0.82);
      border: 1px solid var(--line);
      border-radius: var(--radius-xl);
      padding: 18px 20px;
      box-shadow: var(--shadow-sm);
      backdrop-filter: blur(12px);
    }}
    .topbar-meta {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .user-pill {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 6px 12px;
      background: var(--panel-soft);
      color: var(--text-secondary);
      font-size: 13px;
      font-weight: 700;
    }}
    .user-pill::before {{
      content: "";
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--good);
    }}
    .page-header {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: flex-start;
      margin-bottom: 20px;
      background: linear-gradient(135deg, #ffffff 0%, #f8fbff 100%);
      border: 1px solid var(--line);
      border-radius: var(--radius-xl);
      padding: 24px;
      box-shadow: var(--shadow);
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
    .summary-strip {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }}
    .summary-strip span {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: white;
      padding: 7px 11px;
      color: var(--text-secondary);
      font-size: 13px;
      font-weight: 700;
    }}
    .summary-strip strong {{
      color: var(--text);
    }}
    h1 {{
      font-size: 28px;
      margin: 0;
      letter-spacing: 0;
      font-weight: 800;
      color: var(--text);
    }}
    h2 {{
      font-size: 20px;
      margin: 0 0 16px;
      letter-spacing: 0;
      font-weight: 750;
      color: var(--text);
    }}
    h3 {{
      font-size: 16px;
      margin: 0 0 12px;
      letter-spacing: 0;
      font-weight: 750;
    }}
    .muted {{
      color: var(--muted);
      font-size: 14px;
    }}
    .filters {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(156px, 1fr));
      gap: 12px;
      align-items: end;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      padding: 16px;
      margin-bottom: 20px;
      box-shadow: var(--shadow-sm);
    }}
    .filter-panel {{ background: var(--panel); }}
    label {{
      display: block;
      color: var(--text-secondary);
      font-size: 12px;
      font-weight: 750;
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    select, input {{
      width: 100%;
      height: 42px;
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
      border-radius: 10px;
      padding: 10px 16px;
      background: white;
      cursor: pointer;
      font: inherit;
      font-size: 14px;
      font-weight: 750;
      white-space: nowrap;
      transition: all 0.15s ease;
      box-shadow: var(--shadow-sm);
    }}
    .button:hover {{
      background: var(--panel-soft);
      border-color: #cbd5e1;
      transform: translateY(-1px);
      box-shadow: var(--shadow);
    }}
    .button.primary {{
      background: var(--accent);
      border-color: var(--accent);
      color: white;
      box-shadow: 0 10px 22px -16px var(--accent);
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
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 16px;
    }}
    .kpi {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      padding: 18px;
      min-height: 118px;
      box-shadow: var(--shadow-sm);
      transition: all 0.2s ease;
      position: relative;
      overflow: hidden;
    }}
    .kpi::before {{
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: 4px;
      background: var(--line);
    }}
    .kpi-card {{ background: var(--panel); }}
    .kpi-card .kpi-value {{ display:block;font-size:28px;line-height:1.2;font-weight:700;color:var(--text); }}
    .kpi-card .kpi-label {{ display:block;color:var(--muted);font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:0.04em;margin-top:6px; }}
    .kpi:hover {{
      box-shadow: var(--shadow-md);
      transform: translateY(-1px);
    }}
    .kpi span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      margin-bottom: 10px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .kpi strong {{
      display: block;
      font-size: 28px;
      line-height: 1.2;
      overflow-wrap: anywhere;
      font-weight: 700;
    }}
    .kpi.good::before {{ background: var(--good); }}
    .kpi.bad::before {{ background: var(--bad); }}
    .kpi.warn::before {{ background: var(--warn); }}
    .kpi.action::before {{ background: var(--accent); }}
    .kpi.neutral::before {{ background: var(--accent); }}
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
    .premium-hero {{
      position: relative;
      overflow: hidden;
      display: grid;
      grid-template-columns: minmax(0, 1.5fr) minmax(280px, 0.7fr);
      gap: 22px;
      padding: 28px;
      border: 1px solid #bfdbfe;
      border-radius: var(--radius-xl);
      background:
        radial-gradient(circle at 92% 8%, rgb(15 118 110 / 0.16), transparent 30%),
        linear-gradient(135deg, #ffffff 0%, #eff6ff 54%, #ecfeff 100%);
      box-shadow: var(--shadow-md);
      margin-bottom: 20px;
    }}
    .premium-hero::after {{
      content: "";
      position: absolute;
      inset: auto 24px 0 auto;
      width: 220px;
      height: 220px;
      border-radius: 999px;
      background: rgb(37 99 235 / 0.08);
      transform: translateY(48%);
      pointer-events: none;
    }}
    .hero-content, .hero-panel {{ position: relative; z-index: 1; }}
    .hero-eyebrow {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 12px;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgb(255 255 255 / 0.78);
      border: 1px solid #dbeafe;
      color: var(--accent);
      font-size: 12px;
      font-weight: 850;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .premium-hero h2 {{
      margin: 0 0 10px;
      font-size: 30px;
      line-height: 1.15;
      font-weight: 850;
      color: var(--text);
    }}
    .hero-lead {{
      max-width: 760px;
      margin: 0;
      color: var(--text-secondary);
      font-size: 15px;
    }}
    .hero-panel {{
      display: grid;
      gap: 10px;
      align-content: start;
      border: 1px solid rgb(219 227 239 / 0.9);
      border-radius: var(--radius-lg);
      padding: 16px;
      background: rgb(255 255 255 / 0.82);
      box-shadow: var(--shadow-sm);
      backdrop-filter: blur(10px);
    }}
    .hero-stat {{
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: center;
      padding: 10px 0;
      border-bottom: 1px solid var(--line);
      color: var(--text-secondary);
      font-size: 13px;
      font-weight: 700;
    }}
    .hero-stat:last-child {{ border-bottom: 0; }}
    .hero-stat strong {{
      color: var(--text);
      text-align: right;
      font-size: 14px;
      overflow-wrap: anywhere;
    }}
    .premium-kpi-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 16px;
      margin-bottom: 20px;
    }}
    .premium-kpi {{
      min-height: 150px;
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: var(--radius-xl);
      background:
        linear-gradient(180deg, rgb(255 255 255 / 0.96), rgb(248 250 252 / 0.92));
      box-shadow: var(--shadow-sm);
      position: relative;
      overflow: hidden;
      transition: transform 0.18s ease, box-shadow 0.18s ease;
    }}
    .premium-kpi:hover {{
      transform: translateY(-2px);
      box-shadow: var(--shadow-md);
    }}
    .premium-kpi::before {{
      content: "";
      position: absolute;
      inset: 0 0 auto;
      height: 4px;
      background: var(--accent);
    }}
    .premium-kpi.good::before {{ background: var(--good); }}
    .premium-kpi.bad::before {{ background: var(--bad); }}
    .premium-kpi.warn::before {{ background: var(--warn); }}
    .premium-kpi.neutral::before {{ background: #94a3b8; }}
    .premium-kpi span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 850;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 10px;
    }}
    .premium-kpi strong {{
      display: block;
      color: var(--text);
      font-size: 30px;
      line-height: 1.12;
      font-weight: 850;
      overflow-wrap: anywhere;
    }}
    .premium-kpi small {{
      display: block;
      margin-top: 10px;
      color: var(--text-secondary);
      font-size: 13px;
      line-height: 1.4;
    }}
    .premium-kpi .change {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 4px 9px;
      background: var(--neutral-soft);
      font-weight: 800;
    }}
    .premium-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.25fr) minmax(320px, 0.75fr);
      gap: 20px;
      margin-top: 20px;
    }}
    .premium-section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius-xl);
      padding: 22px;
      box-shadow: var(--shadow-sm);
      min-width: 0;
    }}
    .section-head {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      margin-bottom: 16px;
    }}
    .section-head h2 {{ margin-bottom: 4px; }}
    .attention-list, .event-list, .shortcut-grid, .marketplace-split {{
      display: grid;
      gap: 12px;
    }}
    .attention-item, .event-item, .shortcut-card, .marketplace-panel {{
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      background: var(--panel-soft);
      padding: 14px;
    }}
    .attention-item {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 14px;
      align-items: center;
      border-left: 4px solid var(--accent);
    }}
    .attention-item.good {{ border-left-color: var(--good); }}
    .attention-item.bad {{ border-left-color: var(--bad); }}
    .attention-item.warn {{ border-left-color: var(--warn); }}
    .attention-item strong, .event-item strong, .shortcut-card strong {{
      display: block;
      color: var(--text);
      margin-bottom: 4px;
    }}
    .attention-item p, .event-item p, .shortcut-card p {{
      margin: 0;
      color: var(--text-secondary);
      font-size: 13px;
    }}
    .marketplace-split {{
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .marketplace-panel {{
      background:
        linear-gradient(180deg, #ffffff, #f8fafc);
    }}
    .marketplace-panel-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-bottom: 14px;
    }}
    .marketplace-share {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
    }}
    .mini-stat-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }}
    .mini-stat {{
      border-radius: var(--radius);
      background: white;
      border: 1px solid var(--line);
      padding: 10px;
    }}
    .mini-stat span {{
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 5px;
    }}
    .mini-stat strong {{
      color: var(--text);
      font-size: 16px;
    }}
    .event-item {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      align-items: center;
      background: white;
    }}
    .event-meta {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      margin-top: 6px;
    }}
    .shortcut-grid {{
      grid-template-columns: repeat(5, minmax(0, 1fr));
    }}
    .shortcut-card {{
      display: block;
      color: inherit;
      text-decoration: none;
      background: white;
      transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
    }}
    .shortcut-card:hover {{
      transform: translateY(-2px);
      border-color: #bfdbfe;
      box-shadow: var(--shadow);
    }}
    .analytics-shell {{
      display: grid;
      gap: 20px;
    }}
    .analytics-control {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 14px;
    }}
    .analytics-control .filters {{
      margin: 0;
    }}
    .dashboard-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 20px;
      margin-top: 20px;
    }}
    .band {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      padding: 24px;
      min-width: 0;
      box-shadow: var(--shadow-sm);
      transition: box-shadow 0.2s ease;
    }}
    .section-card, .table-card, .form-card, .alert-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
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
      border: 1px dashed #cbd5e1;
      border-radius: var(--radius-lg);
      padding: 24px;
      font-weight: 650;
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
      border: 1px dashed #cbd5e1;
      border-radius: var(--radius-lg);
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
      border-collapse: separate;
      border-spacing: 0;
      font-size: 14px;
    }}
    .table-wrap {{
      width: 100%;
      overflow-x: auto;
      border-radius: var(--radius);
      border: 1px solid var(--line);
      background: var(--panel);
    }}
    .table th, .table td {{
      padding: 13px 14px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    .table thead {{
      background: #f8fafc;
    }}
    .table th {{
      color: var(--text-secondary);
      font-weight: 800;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }}
    .table tbody tr {{
      transition: background 0.15s ease;
    }}
    .table tbody tr:hover {{
      background: #f8fbff;
    }}
    .table tbody tr:last-child td {{ border-bottom: 0; }}
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
      font-weight: 800;
      white-space: nowrap;
      border: 1px solid transparent;
    }}
    .badge.good {{ background: var(--good-soft); color: #047857; border-color: #bbf7d0; }}
    .badge.bad {{ background: var(--bad-soft); color: #b91c1c; border-color: #fecaca; }}
    .badge.warn {{ background: var(--warn-soft); color: #92400e; border-color: #fde68a; }}
    .badge.action {{ background: var(--accent-soft); color: var(--accent); border-color: #bfdbfe; }}
    .badge.wb {{ background: #f5f3ff; color: var(--wb); border-color: #ddd6fe; }}
    .badge.ozon {{ background: #dbeafe; color: var(--ozon); border-color: #bfdbfe; }}
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
    .mp-logo {{
      display: inline-grid;
      place-items: center;
      width: 20px;
      height: 20px;
      border-radius: 5px;
      color: #fff;
      font-size: 10px;
      font-weight: 900;
      line-height: 1;
    }}
    .marketplace-badge.wb .mp-logo {{ background: #7c3aed; }}
    .marketplace-badge.ozon .mp-logo {{ background: #2563eb; }}
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
      font-weight: 800;
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
      border-radius: 999px;
      padding: 10px 14px;
      font-size: 14px;
      font-weight: 750;
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
      .shell {{ grid-template-columns: 230px minmax(0, 1fr); }}
      .filters {{ grid-template-columns: repeat(2, minmax(150px, 1fr)); }}
      .kpi-grid {{ grid-template-columns: repeat(2, minmax(160px, 1fr)); }}
      .premium-hero {{ grid-template-columns: 1fr; }}
      .premium-kpi-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .premium-grid {{ grid-template-columns: 1fr; }}
      .shortcut-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .dashboard-grid {{ grid-template-columns: 1fr; }}
      .detail-grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 760px) {{
      .shell {{ grid-template-columns: 1fr; }}
      aside {{
        position: static;
        height: auto;
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }}
      main {{ padding: 20px; }}
      .filters {{ grid-template-columns: 1fr; }}
      .topbar {{
        align-items: flex-start;
        flex-direction: column;
      }}
      .topbar-meta {{ justify-content: flex-start; }}
      .page-header {{
        flex-direction: column;
      }}
      nav {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 4px;
      }}
      .nav-title {{ grid-column: 1 / -1; }}
    }}
    @media (max-width: 520px) {{
      .kpi-grid {{ grid-template-columns: 1fr; }}
      .premium-kpi-grid, .marketplace-split, .mini-stat-grid, .shortcut-grid {{
        grid-template-columns: 1fr;
      }}
      .premium-hero h2 {{ font-size: 24px; }}
      .premium-hero, .premium-section {{ padding: 18px; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <div class="brand">MP Control</div>
      <nav>
        {_nav(active_path)}
      </nav>
    </aside>
    <main>
      <div class="topbar">
        <div>
          <h1>{safe_title}</h1>
          <div class="muted">Операционный кабинет Wildberries и Ozon</div>
        </div>
        <div class="topbar-meta">
          <span class="user-pill">{safe_user}</span>
          <a class="button" href="/web/logout">Выйти</a>
        </div>
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
            icon = escape(NAV_ICONS.get(label, "•"))
            links.append(
                f'<a{active} href="{href}"><span class="nav-icon">{icon}</span>'
                f"<span>{escape(label)}</span></a>"
            )
        groups.append(
            '<div class="nav-group">'
            f'<div class="nav-title">{escape(title)}</div>' + "\n".join(links) + "</div>"
        )
    return "\n".join(groups)
