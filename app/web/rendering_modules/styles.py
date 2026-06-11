"""version: 1.1.0
description: CSS styles for MP Control web rendering – premium redesign.
updated: 2026-06-09
"""

# ruff: noqa: E501

__all__ = [
    "_css",
]


def _css() -> str:
    return """
    :root {
      color-scheme: light;
      --bg: #f5f7fc;
      --bg-card: #ffffff;
      --bg-muted: #f1f4f9;
      --bg-hover: #eef1f6;
      --bg-sidebar: #fbfcfe;
      --bg-sidebar-active: #eef3fe;
      --bg-sidebar-hover: #f2f5fa;
      --text: #0b1a33;
      --text-secondary: #475569;
      --text-muted: #94a3b8;
      --border: #e2e8f0;
      --border-light: #edf2f7;
      --accent: #2563eb;
      --accent-hover: #1d4ed8;
      --accent-soft: #dbeafe;
      --accent-bg: #eff6ff;
      --success: #059669;
      --success-soft: #ecfdf5;
      --success-border: #a7f3d0;
      --danger: #dc2626;
      --danger-soft: #fef2f2;
      --danger-border: #fecaca;
      --warning: #d97706;
      --warning-soft: #fffbeb;
      --warning-border: #fde68a;
      --info: #2563eb;
      --info-soft: #eff6ff;
      --info-border: #bfdbfe;
      --wb: #7c3aed;
      --wb-soft: #f5f3ff;
      --wb-border: #ddd6fe;
      --ozon: #2563eb;
      --ozon-soft: #eff6ff;
      --ozon-border: #bfdbfe;
      --shadow-xs: 0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 1px 0 rgb(15 23 42 / 0.02);
      --shadow-sm: 0 1px 3px 0 rgb(15 23 42 / 0.05), 0 1px 2px -1px rgb(15 23 42 / 0.03);
      --shadow: 0 4px 6px -2px rgb(15 23 42 / 0.05), 0 2px 4px -2px rgb(15 23 42 / 0.03);
      --shadow-md: 0 10px 20px -5px rgb(15 23 42 / 0.06), 0 4px 8px -6px rgb(15 23 42 / 0.03);
      --shadow-lg: 0 20px 30px -8px rgb(15 23 42 / 0.08), 0 8px 12px -6px rgb(15 23 42 / 0.04);
      --radius-sm: 6px;
      --radius: 10px;
      --radius-lg: 14px;
      --radius-xl: 18px;
      --radius-full: 999px;
      --sidebar-w: 300px;
      --topbar-h: 56px;
      --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', 'Roboto', 'Helvetica Neue', Arial, sans-serif;
      --font-mono: ui-monospace, 'SF Mono', 'Cascadia Code', 'Source Code Pro', Menlo, Consolas, monospace;
      --transition-fast: 0.15s cubic-bezier(0.4, 0, 0.2, 1);
      --transition: 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    }
    *, *::before, *::after { box-sizing: border-box; }
    html { -webkit-text-size-adjust: 100%; scroll-behavior: smooth; }
    body {
      margin: 0;
      font-family: var(--font);
      background: var(--bg);
      color: var(--text);
      font-size: 14px;
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }
    a { color: var(--accent); text-decoration: none; transition: color var(--transition-fast); }
    a:hover { color: var(--accent-hover); }
    h1 { font-size: 22px; font-weight: 750; margin: 0; letter-spacing: -0.02em; color: var(--text); }
    h2 { font-size: 17px; font-weight: 700; margin: 0 0 10px; letter-spacing: -0.01em; color: var(--text); }
    h3 { font-size: 14px; font-weight: 700; margin: 0 0 6px; color: var(--text); }
    p { margin: 0 0 8px; color: var(--text-secondary); }
    .muted { color: var(--text-muted); font-size: 13px; }

    /* ── Page animation ── */
    @keyframes fadeInUp {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .page-fade-in {
      animation: fadeInUp 0.3s ease-out;
    }

    /* ── Shell ── */
    .shell {
      display: grid;
      grid-template-columns: var(--sidebar-w) minmax(0, 1fr);
      min-height: 100vh;
    }
    body.nav-open { overflow: hidden; }
    body.nav-open .shell::before {
      content: "";
      position: fixed;
      inset: 0;
      background: rgb(15 23 42 / 0.4);
      z-index: 190;
      animation: fadeIn 0.2s ease;
    }
    @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
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
      padding: 16px 14px 18px 12px;
      z-index: 100;
      scrollbar-width: thin;
      scrollbar-color: var(--border) transparent;
      transition: left var(--transition);
    }
    aside::-webkit-scrollbar { width: 4px; }
    aside::-webkit-scrollbar-track { background: transparent; }
    aside::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
    aside::-webkit-scrollbar-thumb:hover { background: #cbd5e1; }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 4px 8px 16px;
      margin-bottom: 8px;
      border-bottom: 1px solid var(--border-light);
      position: sticky;
      top: 0;
      background: var(--bg-sidebar);
      z-index: 1;
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
      box-shadow: 0 2px 6px rgb(37 99 235 / 0.2);
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
      transition: all var(--transition-fast);
      line-height: 1.3;
      min-height: 36px;
      overflow-wrap: anywhere;
      position: relative;
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
    nav a.active::before {
      content: "";
      position: absolute;
      left: -12px;
      top: 50%;
      transform: translateY(-50%);
      width: 3px;
      height: 20px;
      border-radius: 0 3px 3px 0;
      background: var(--accent);
      box-shadow: 0 0 6px rgb(37 99 235 / 0.3);
    }
    .nav-icon {
      display: inline-grid;
      place-items: center;
      width: 28px;
      height: 28px;
      flex-shrink: 0;
      border-radius: var(--radius-sm);
      color: var(--text-muted);
      transition: all var(--transition-fast);
    }
    nav a:hover .nav-icon { color: var(--text-secondary); }
    nav a.active .nav-icon { color: var(--accent); background: var(--accent-soft); border-radius: 6px; }
    .nav-group { margin-top: 14px; }
    .nav-group:first-child { margin-top: 0; }
    .nav-title {
      color: var(--text-muted);
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 4px 10px 8px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .nav-title::after {
      content: "";
      flex: 1;
      height: 1px;
      background: var(--border-light);
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
      box-shadow: 0 1px 2px rgb(15 23 42 / 0.02);
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
      border: 1px solid var(--border-light);
    }
    .user-pill::before {
      content: "";
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--success);
      box-shadow: 0 0 0 2px var(--success-soft);
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
      transition: all var(--transition-fast);
    }
    .sidebar-toggle:hover {
      background: var(--bg-hover);
      border-color: #cbd5e1;
      color: var(--text);
    }

    /* ── Main ── */
    main {
      padding: 24px 28px 48px;
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
      transition: all var(--transition-fast);
      box-shadow: var(--shadow-xs);
    }
    .btn:hover, .button:hover {
      background: var(--bg-hover);
      border-color: #cbd5e1;
      transform: translateY(-1px);
      box-shadow: var(--shadow-sm);
    }
    .btn:active, .button:active {
      transform: translateY(0);
      box-shadow: var(--shadow-xs);
    }
    .btn-primary, .button.primary, .primary-button {
      background: linear-gradient(135deg, var(--accent), #1d4ed8);
      border-color: var(--accent);
      color: #fff;
      box-shadow: 0 1px 3px rgb(37 99 235 / 0.25), 0 1px 2px rgb(37 99 235 / 0.15);
    }
    .btn-primary:hover, .button.primary:hover, .primary-button:hover {
      background: linear-gradient(135deg, var(--accent-hover), #1e40af);
      border-color: var(--accent-hover);
      box-shadow: 0 2px 6px rgb(37 99 235 / 0.3), 0 1px 2px rgb(37 99 235 / 0.2);
    }
    .btn-ghost { background: transparent; border-color: transparent; box-shadow: none; }
    .btn-ghost:hover { background: var(--bg-hover); border-color: transparent; transform: none; box-shadow: none; }
    .btn-sm { height: 30px; padding: 0 10px; font-size: 12px; }
    .btn-danger, .danger-button { background: linear-gradient(135deg, var(--danger), #b91c1c); border-color: var(--danger); color: #fff; }
    .btn-danger:hover, .danger-button:hover { background: linear-gradient(135deg, #b91c1c, #991b1b); }
    .secondary-button { background: var(--bg-card); }

    /* ── Page Header ── */
    .page-header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      margin-bottom: 16px;
      background: linear-gradient(135deg, var(--bg-card) 0%, #f8faff 100%);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 20px 24px;
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
      margin-top: 14px;
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
      box-shadow: var(--shadow-xs);
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
      padding: 16px 18px;
      margin-bottom: 16px;
      box-shadow: var(--shadow-sm);
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
      transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
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
      transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
    }
    textarea:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-soft);
    }
    textarea:hover { border-color: #cbd5e1; }

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
      padding: 16px 18px;
      box-shadow: var(--shadow-xs);
      position: relative;
      overflow: hidden;
      transition: all var(--transition);
    }
    .kpi:hover {
      box-shadow: var(--shadow-md);
      transform: translateY(-2px);
    }
    .kpi::before {
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: 3px;
      background: var(--border);
      border-radius: 0 2px 2px 0;
    }
    .kpi::after {
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(135deg, transparent 60%, rgb(37 99 235 / 0.02));
      pointer-events: none;
    }
    .kpi span {
      display: block;
      color: var(--text-muted);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 6px;
      position: relative;
      z-index: 1;
    }
    .kpi strong {
      display: block;
      font-size: 24px;
      line-height: 1.2;
      font-weight: 750;
      overflow-wrap: anywhere;
      position: relative;
      z-index: 1;
      letter-spacing: -0.02em;
    }
    .kpi.good::before { background: linear-gradient(180deg, var(--success), #34d399); }
    .kpi.bad::before { background: linear-gradient(180deg, var(--danger), #f87171); }
    .kpi.warn::before { background: linear-gradient(180deg, var(--warning), #fbbf24); }
    .kpi.action::before { background: linear-gradient(180deg, var(--accent), #60a5fa); }
    .kpi.neutral::before { background: linear-gradient(180deg, var(--accent), #93c5fd); }
    .kpi.good strong { color: var(--success); }
    .kpi.bad strong { color: var(--danger); }
    .kpi.warn strong { color: var(--warning); }
    .kpi-card { background: var(--bg-card); }
    .kpi-card .kpi-value { display: block; font-size: 24px; line-height: 1.2; font-weight: 750; color: var(--text); letter-spacing: -0.02em; }
    .kpi-card .kpi-label { display: block; color: var(--text-muted); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; margin-top: 4px; }
    .change {
      display: inline-flex;
      align-items: center;
      gap: 3px;
      margin-top: 8px;
      font-size: 12px;
      color: var(--text-muted);
      font-weight: 500;
      position: relative;
      z-index: 1;
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
      padding: 18px;
      box-shadow: var(--shadow-xs);
      position: relative;
      overflow: hidden;
      transition: all var(--transition);
      min-height: 120px;
    }
    .premium-kpi:hover {
      box-shadow: var(--shadow-md);
      transform: translateY(-2px);
    }
    .premium-kpi::before {
      content: "";
      position: absolute;
      inset: 0 0 auto;
      height: 3px;
      background: linear-gradient(90deg, var(--accent), #60a5fa);
    }
    .premium-kpi.good::before { background: linear-gradient(90deg, var(--success), #34d399); }
    .premium-kpi.bad::before { background: linear-gradient(90deg, var(--danger), #f87171); }
    .premium-kpi.warn::before { background: linear-gradient(90deg, var(--warning), #fbbf24); }
    .premium-kpi.neutral::before { background: linear-gradient(90deg, var(--text-muted), #cbd5e1); }
    .premium-kpi::after {
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(135deg, transparent 60%, rgb(37 99 235 / 0.02));
      pointer-events: none;
    }
    .premium-kpi span {
      display: block;
      color: var(--text-muted);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 8px;
      position: relative;
      z-index: 1;
    }
    .premium-kpi strong {
      display: block;
      color: var(--text);
      font-size: 26px;
      line-height: 1.15;
      font-weight: 750;
      overflow-wrap: anywhere;
      letter-spacing: -0.02em;
      position: relative;
      z-index: 1;
    }
    .premium-kpi small {
      display: block;
      margin-top: 8px;
      color: var(--text-secondary);
      font-size: 12px;
      line-height: 1.4;
      position: relative;
      z-index: 1;
    }
    .premium-kpi .change {
      display: inline-flex;
      align-items: center;
      border-radius: var(--radius-full);
      padding: 2px 8px;
      background: var(--bg-muted);
      font-weight: 700;
      font-size: 11px;
      position: relative;
      z-index: 1;
    }

    /* ── Hero ── */
    .premium-hero {
      position: relative;
      overflow: hidden;
      display: grid;
      grid-template-columns: minmax(0, 1.5fr) minmax(260px, 0.7fr);
      gap: 20px;
      padding: 28px 32px;
      border: 1px solid var(--accent-soft);
      border-radius: var(--radius-xl);
      background: linear-gradient(135deg, #ffffff 0%, #f6fbff 45%, #eef6ff 100%);
      box-shadow: var(--shadow-sm);
      margin-bottom: 16px;
    }
    .premium-hero::after {
      content: "";
      position: absolute;
      inset: auto -60px -60px auto;
      width: 220px;
      height: 220px;
      border-radius: 50%;
      background: radial-gradient(circle, rgb(37 99 235 / 0.06) 0%, transparent 70%);
      pointer-events: none;
    }
    .premium-hero::before {
      content: "";
      position: absolute;
      inset: -40px auto auto -40px;
      width: 140px;
      height: 140px;
      border-radius: 50%;
      background: radial-gradient(circle, rgb(37 99 235 / 0.03) 0%, transparent 70%);
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
      background: linear-gradient(135deg, var(--accent-bg), #e8f4ff);
      border: 1px solid var(--accent-soft);
      color: var(--accent);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .premium-hero h2 {
      margin: 0 0 8px;
      font-size: 24px;
      line-height: 1.2;
      font-weight: 800;
      letter-spacing: -0.02em;
    }
    .hero-lead {
      max-width: 680px;
      margin: 0;
      color: var(--text-secondary);
      font-size: 14px;
      line-height: 1.6;
    }
    .hero-panel {
      display: grid;
      gap: 8px;
      align-content: start;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 16px;
      background: rgb(255 255 255 / 0.9);
      box-shadow: var(--shadow-sm);
      backdrop-filter: blur(4px);
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
      padding: 22px;
      box-shadow: var(--shadow-xs);
      margin-bottom: 12px;
      transition: box-shadow var(--transition);
    }
    .band:hover, .section-card:hover, .table-card:hover {
      box-shadow: var(--shadow-sm);
    }
    .premium-section {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 22px;
      box-shadow: var(--shadow-xs);
      min-width: 0;
      transition: box-shadow var(--transition);
    }
    .premium-section:hover {
      box-shadow: var(--shadow-sm);
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
      background: var(--bg-card);
      padding: 14px 16px;
      transition: all var(--transition-fast);
    }
    .attention-item:hover {
      box-shadow: var(--shadow-xs);
      border-color: #cbd5e1;
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
      padding: 12px 14px;
      transition: all var(--transition-fast);
    }
    .event-item:hover {
      border-color: #cbd5e1;
      box-shadow: var(--shadow-xs);
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
      padding: 14px;
      transition: all var(--transition);
    }
    .shortcut-card:hover {
      border-color: var(--accent-soft);
      box-shadow: var(--shadow-md);
      transform: translateY(-2px);
      color: inherit;
    }

    /* ── Marketplace ── */
    .marketplace-split { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .marketplace-panel {
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: var(--bg-card);
      padding: 16px;
      transition: box-shadow var(--transition-fast);
    }
    .marketplace-panel:hover {
      box-shadow: var(--shadow-xs);
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
      padding: 8px 10px;
      transition: background var(--transition-fast);
    }
    .mini-stat:hover { background: var(--bg-hover); }
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
    .table thead::after {
      content: "";
      position: absolute;
      bottom: 0;
      left: 0;
      right: 0;
      height: 1px;
      background: var(--border);
    }
    .table th {
      color: var(--text-muted);
      font-weight: 700;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      white-space: nowrap;
      border-bottom: none;
      padding: 11px 12px;
    }
    .table tbody tr { transition: background var(--transition-fast); }
    .table tbody tr:hover { background: var(--bg-hover); }
    .table tbody tr:nth-child(even) { background: #fafbfd; }
    .table tbody tr:nth-child(even):hover { background: var(--bg-hover); }
    .table tbody tr:last-child td { border-bottom: 0; }
    .table td.num, .table th.num { text-align: right; font-variant-numeric: tabular-nums; }
    .table a {
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
    }
    .table a:hover { color: var(--accent-hover); text-decoration: underline; }
    .table td:first-child { padding-left: 14px; }
    .table th:first-child { padding-left: 14px; }
    .table td:last-child { padding-right: 14px; }
    .table th:last-child { padding-right: 14px; }

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
    .badge.action { background: var(--accent-soft); color: var(--accent); border-color: var(--info-border); }
    .badge.wb { background: var(--wb-soft); color: var(--wb); border-color: var(--wb-border); }
    .badge.ozon { background: var(--ozon-soft); color: var(--ozon); border-color: var(--ozon-border); }
    .marketplace-logo {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      object-fit: contain;
      vertical-align: middle;
      flex-shrink: 0;
    }
    .marketplace-logo-sm { width: 18px; height: 18px; }
    .marketplace-logo-md { width: 28px; height: 28px; }
    .marketplace-logo-lg { width: 40px; height: 40px; }
    .marketplace-logo-inline { margin-right: 4px; }
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
      overflow: hidden;
    }
    .mp-logo img { width: 100%; height: 100%; display: block; }
    .marketplace-badge.wb .mp-logo { background: linear-gradient(135deg, var(--wb), #6d28d9); }
    .marketplace-badge.ozon .mp-logo { background: linear-gradient(135deg, var(--ozon), #1d4ed8); }
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
      transition: all var(--transition-fast);
    }
    .chart-empty:hover {
      border-color: #cbd5e1;
      background: var(--bg-hover);
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
    .progress-card { border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 12px; background: var(--bg-muted); }
    .progress-card div:first-child { display: flex; justify-content: space-between; gap: 8px; align-items: center; font-size: 12px; }
    .progress-track { height: 6px; border-radius: var(--radius-full); background: var(--border); overflow: hidden; margin: 8px 0 4px; }
    .progress-track span { display: block; height: 100%; background: linear-gradient(90deg, var(--accent), #60a5fa); border-radius: var(--radius-full); transition: width 0.4s ease; }

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
      gap: 4px;
      margin-bottom: 16px;
    }
    .subnav a {
      color: var(--text-secondary);
      text-decoration: none;
      border: 1px solid var(--border);
      background: var(--bg-card);
      border-radius: var(--radius-full);
      padding: 6px 14px;
      font-size: 12px;
      font-weight: 600;
      transition: all var(--transition-fast);
    }
    .subnav a:hover {
      background: var(--bg-hover);
      border-color: #cbd5e1;
      color: var(--text);
    }
    .subnav a.active {
      background: linear-gradient(135deg, var(--accent), #1d4ed8);
      border-color: var(--accent);
      color: #fff;
      box-shadow: 0 1px 3px rgb(37 99 235 / 0.2);
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
      padding: 16px;
      line-height: 1.6;
    }
    .wide { grid-column: 1 / -1; }
    .empty-state {
      min-height: 140px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      text-align: center;
      color: var(--text-muted);
      background: var(--bg-muted);
      border: 1px dashed var(--border);
      border-radius: var(--radius);
      padding: 24px;
      font-weight: 600;
      font-size: 13px;
      transition: all var(--transition-fast);
    }
    .empty-state:hover {
      border-color: #cbd5e1;
      background: var(--bg-hover);
    }
    .empty-state.compact { min-height: 80px; padding: 14px; font-size: 12px; }
    .empty-state strong { display: block; color: var(--text-secondary); margin-bottom: 4px; font-size: 14px; }
    .empty-state span { display: block; color: var(--text-muted); font-weight: 500; }

    /* ── Notices ── */
    .notice {
      padding: 12px 14px;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border);
      background: var(--bg-muted);
      color: var(--text-secondary);
      font-size: 13px;
      margin-bottom: 12px;
    }
    .notice.success { background: var(--success-soft); border-color: var(--success-border); color: #047857; }
    .notice.danger { background: var(--danger-soft); border-color: var(--danger-border); color: #b91c1c; }
    .notice.warning { background: var(--warning-soft); border-color: var(--warning-border); color: #92400e; }

    /* ── Tiny Button ── */
    .button-tiny {
      display: inline-flex;
      align-items: center;
      height: 26px;
      padding: 0 8px;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--bg-card);
      color: var(--text-secondary);
      font: inherit;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      text-decoration: none;
      transition: all var(--transition-fast);
    }
    .button-tiny:hover { background: var(--bg-hover); border-color: #cbd5e1; color: var(--text); }

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
    .interface-error {
      position: fixed;
      left: 50%;
      top: 12px;
      transform: translateX(-50%);
      width: min(560px, calc(100vw - 24px));
      z-index: 500;
      padding: 12px 14px;
      border: 1px solid var(--danger-border);
      border-radius: var(--radius);
      background: #fff;
      color: var(--danger);
      box-shadow: var(--shadow-lg);
      font-weight: 700;
      text-align: center;
    }

    /* ── Smooth scrollbar ── */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #9ca3af; }

    /* ── Responsive ── */
    @media (max-width: 1200px) {
      .shell { grid-template-columns: var(--sidebar-w) minmax(0, 1fr); }
      .premium-kpi-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .premium-grid { grid-template-columns: 1fr; }
      .dashboard-grid { grid-template-columns: 1fr; }
      .detail-grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 900px) {
      .shell { grid-template-columns: 1fr; }
      aside {
        position: fixed;
        left: calc(var(--sidebar-w) * -1 - 16px);
        top: 0;
        width: min(var(--sidebar-w), 88vw);
        height: 100vh;
        z-index: 200;
        transition: left 0.25s cubic-bezier(0.4, 0, 0.2, 1);
        box-shadow: var(--shadow-lg);
      }
      aside.is-open { left: 0; }
      .sidebar-toggle { display: inline-flex; }
      main { padding: 16px; }
      .topbar { padding: 0 16px; }
      .filters { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
      .kpi-grid { grid-template-columns: repeat(2, minmax(140px, 1fr)); }
      .premium-kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .premium-hero { grid-template-columns: 1fr; padding: 20px; }
      .shortcut-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .marketplace-split { grid-template-columns: 1fr; }
      nav a.active::before { left: -14px; }
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
      .kpi strong { font-size: 20px; }
      .premium-kpi strong { font-size: 22px; }
    }

    /* ── Sync Center ── */
    .sync-btn-grid {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .sync-btn-grid .btn, .sync-btn-grid .button-tiny {
      transition: all var(--transition-fast);
    }
    .sync-btn-grid .btn:disabled, .sync-btn-grid .btn.disabled,
    .sync-btn-grid .button-tiny:disabled {
      opacity: 0.5;
      cursor: not-allowed;
      pointer-events: auto;
    }
    .sync-btn-grid .btn.running {
      background: var(--accent-soft);
      color: var(--accent);
      border-color: var(--accent);
      position: relative;
      padding-left: 28px;
    }
    .sync-btn-grid .btn.running::before {
      content: "";
      position: absolute;
      left: 8px;
      width: 14px;
      height: 14px;
      border: 2px solid var(--accent);
      border-top-color: transparent;
      border-radius: 50%;
      animation: sync-spin 0.8s linear infinite;
    }
    @keyframes sync-spin {
      to { transform: rotate(360deg); }
    }
    .sync-btn-grid .btn.success-flash {
      background: var(--success-soft);
      color: #047857;
      border-color: var(--success-border);
    }
    .sync-btn-grid .btn.error-flash {
      background: var(--danger-soft);
      color: #b91c1c;
      border-color: var(--danger-border);
    }

    /* ── Toast notifications ── */
    #toast-container {
      position: fixed;
      top: 16px;
      right: 16px;
      z-index: 1000;
      display: flex;
      flex-direction: column;
      gap: 8px;
      max-width: 400px;
    }
    .toast {
      padding: 12px 16px;
      border-radius: var(--radius);
      background: var(--bg-card);
      border: 1px solid var(--border);
      box-shadow: var(--shadow-lg);
      font-size: 13px;
      font-weight: 600;
      animation: toast-in 0.3s ease-out;
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 280px;
    }
    .toast.success { border-left: 4px solid var(--success); color: #047857; }
    .toast.error { border-left: 4px solid var(--danger); color: #b91c1c; }
    .toast.warning { border-left: 4px solid var(--warning); color: #92400e; }
    .toast.info { border-left: 4px solid var(--accent); color: var(--accent); }
    @keyframes toast-in {
      from { opacity: 0; transform: translateX(20px); }
      to { opacity: 1; transform: translateX(0); }
    }
    @keyframes toast-out {
      from { opacity: 1; transform: translateX(0); }
      to { opacity: 0; transform: translateX(20px); }
    }

    /* ── Summary Cards ── */
    .orders-summary {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }
    .summary-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 14px 16px;
      box-shadow: var(--shadow-xs);
      position: relative;
      overflow: hidden;
      transition: all var(--transition);
    }
    .summary-card:hover {
      box-shadow: var(--shadow-sm);
      transform: translateY(-1px);
    }
    .summary-card::before {
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: 3px;
      background: var(--accent);
      border-radius: 0 2px 2px 0;
    }
    .summary-card.good::before { background: var(--success); }
    .summary-card.bad::before { background: var(--danger); }
    .summary-card.warn::before { background: var(--warning); }
    .summary-card.neutral::before { background: var(--text-muted); }
    .summary-label {
      display: block;
      color: var(--text-muted);
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 4px;
    }
    .summary-value {
      display: block;
      font-size: 20px;
      font-weight: 750;
      line-height: 1.2;
      letter-spacing: -0.02em;
      color: var(--text);
    }
    .summary-card.good .summary-value { color: var(--success); }
    .summary-card.bad .summary-value { color: var(--danger); }
    .summary-card.warn .summary-value { color: var(--warning); }
    .summary-note {
      display: block;
      color: var(--text-muted);
      font-size: 11px;
      margin-top: 2px;
    }

    /* ── Sync Bar ── */
    .sync-bar {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      padding: 10px 14px;
      margin-bottom: 14px;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: var(--bg-card);
      box-shadow: var(--shadow-xs);
    }
    .sync-bar-main {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .sync-bar-acc {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-left: auto;
    }

    /* ── Orders Toolbar ── */
    .orders-toolbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 12px;
    }
    .orders-toolbar-right {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    /* ── Orders Table ── */
    .orders-table th, .orders-table td {
      white-space: nowrap;
    }
    .orders-table .cell-title {
      max-width: 220px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .orders-table .cell-ids {
      max-width: 180px;
      font-size: 12px;
      line-height: 1.5;
    }
    .orders-table .cell-costs {
      font-size: 12px;
    }
    .orders-table .cell-status {
      min-width: 120px;
    }
    .orders-table .cell-status > div {
      margin-bottom: 2px;
    }
    .orders-table .cell-source {
      font-size: 11px;
      color: var(--text-muted);
    }
    .order-row {
      cursor: pointer;
    }
    .order-row:hover {
      background: var(--bg-hover) !important;
    }
    .order-detail-row td {
      padding: 0 !important;
      border-bottom: 1px solid var(--border-light);
    }
    .order-detail-body {
      padding: 14px 18px;
      background: #fafbfd;
      border-top: 1px dashed var(--border);
    }
    .detail-grid-compact {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 6px 16px;
      font-size: 13px;
    }
    .detail-grid-compact div {
      padding: 3px 0;
    }
    .detail-grid-compact strong {
      color: var(--text-secondary);
      font-weight: 600;
    }
    .detail-actions {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }

    /* ── Tone colors ── */
    .tone-good { color: var(--success); font-weight: 600; }
    .tone-bad { color: var(--danger); font-weight: 600; }
    .tone-warn { color: var(--warning); font-weight: 600; }

    /* ── Disabled button ── */
    .button.disabled, .button:disabled {
      opacity: 0.4;
      cursor: not-allowed;
      pointer-events: none;
    }

    /* ── Pagination ── */
    .pagination-bar .button {
      min-width: 32px;
      height: 32px;
      padding: 0 8px;
      font-size: 12px;
    }

    /* ── Quick Periods ── */
    .quick-periods .button {
      height: 28px;
      font-size: 11px;
      padding: 0 10px;
    }

    /* ── Responsive table ── */
    @media (max-width: 900px) {
      .orders-table .cell-costs,
      .orders-table .cell-source {
        display: none;
      }
      .orders-summary {
        grid-template-columns: repeat(3, minmax(120px, 1fr));
      }
      .orders-table .cell-ids {
        max-width: 120px;
      }
      .orders-table .cell-title {
        max-width: 140px;
      }
    }
    @media (max-width: 560px) {
      .orders-summary {
        grid-template-columns: repeat(2, minmax(100px, 1fr));
      }
      .summary-value {
        font-size: 16px;
      }
      .sync-bar {
        flex-direction: column;
        align-items: flex-start;
      }
      .sync-bar-acc {
        margin-left: 0;
      }
      .orders-table .cell-ids {
        max-width: 80px;
        font-size: 11px;
      }
      .detail-grid-compact {
        grid-template-columns: 1fr;
      }
    }
    """
