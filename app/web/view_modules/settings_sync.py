"""version: 1.0.0
description: Settings → Synchronization tab — professional sync dashboard view.
updated: 2026-06-12
"""

# ruff: noqa: E501

import json
from html import escape
from typing import Any

from app.utils.datetime import format_datetime_for_user

__all__ = ["_sync_tab"]

# ── Sync type metadata ──────────────────────────────────────────────────────

SYNC_ICONS: dict[str, str] = {
    "orders": "📦",
    "sales": "💰",
    "stocks": "🏭",
    "products": "🛍️",
    "prices": "🏷️",
    "commissions": "📊",
    "financial_reports": "📑",
    "auto_promotions": "🎯",
    "reviews": "⭐",
}

SYNC_DESCRIPTIONS: dict[str, str] = {
    "orders": "Загрузка новых заказов FBS и обновление статусов по WB и Ozon",
    "sales": "Синхронизация данных о продажах и выкупах за выбранный период",
    "stocks": "Проверка актуальных остатков товаров на складах маркетплейсов",
    "products": "Загрузка карточек товаров, характеристик и изображений",
    "prices": "Синхронизация актуальных цен, скидок и акционных предложений",
    "commissions": "Загрузка тарифов и комиссий маркетплейсов",
    "financial_reports": "Загрузка финансовых отчётов, детализации выплат и расчётов",
    "auto_promotions": "Синхронизация автоматических акций и специальных предложений",
    "reviews": "Загрузка отзывов покупателей и вопросов о товарах",
}

# Mapping from UserSyncStatusService type → WebSyncRunService trigger key
SYNC_TRIGGER_KEYS: dict[str, str | None] = {
    "orders": "orders",
    "sales": "sales",
    "stocks": "stocks",
    "products": "products",
    "prices": None,
    "commissions": None,
    "financial_reports": "finances",
    "auto_promotions": "wb_promotions",
    "reviews": None,
}

STATUS_BADGE: dict[str, tuple[str, str]] = {
    "success": ("success", "Успешно"),
    "error": ("error", "Ошибка"),
    "pending": ("pending", "Ожидает запуска"),
    "running": ("running", "Выполняется"),
    "warning": ("warning", "Предупреждения"),
    "skipped": ("warning", "Пропущено"),
    "disabled": ("disabled", "Отключено"),
}

# ── Helpers ─────────────────────────────────────────────────────────────────

def _fmt_dt(dt: Any, timezone: str) -> str:
    if dt is None:
        return "Пока не запускалось"
    return format_datetime_for_user(dt, timezone, "%d.%m.%Y %H:%M")


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "н/д"
    if seconds < 60:
        return f"{round(seconds)} сек"
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m} мин {s} сек" if s else f"{m} мин"


def _fmt_interval(minutes: int) -> str:
    if minutes < 60:
        return f"каждые {minutes} мин"
    h = minutes // 60
    return "каждый час" if h == 1 else f"каждые {h} ч"


def _recommendations(status: str, error_msg: str | None) -> list[str]:
    if status == "pending":
        return [
            "Синхронизация ещё не запускалась — это нормально для нового аккаунта.",
            "Дождитесь планового запуска или нажмите «Запустить».",
        ]
    if status not in ("error", "warning"):
        return ["Синхронизация работает в штатном режиме."]
    if not error_msg:
        return [
            "Проверьте подключение кабинета маркетплейса в разделе «Маркетплейсы».",
            "Попробуйте запустить синхронизацию вручную.",
            "Если ошибка повторяется — обратитесь в службу поддержки.",
        ]
    err = error_msg.lower()
    if "auth" in err or "401" in err or "403" in err:
        return [
            "Ошибка авторизации. Проверьте API-ключ в разделе «Маркетплейсы».",
            "Возможно, ключ был отозван — создайте новый в личном кабинете WB или Ozon.",
            "Если ошибка повторяется — обратитесь в службу поддержки.",
        ]
    if "api" in err or "key" in err or "token" in err:
        return [
            "Проверьте, что API-ключ маркетплейса активен и не истёк.",
            "Перейдите в «Настройки → Маркетплейсы» и проверьте статус ключа.",
        ]
    if "timeout" in err or "timed out" in err:
        return [
            "Маркетплейс временно недоступен. Попробуйте повторить позже.",
            "Если ошибка повторяется несколько часов — обратитесь в поддержку.",
        ]
    if "connect" in err or "connection" in err or "network" in err:
        return [
            "Проблема с подключением к API маркетплейса.",
            "Повторите синхронизацию через несколько минут.",
        ]
    return [
        "Проверьте подключение кабинета маркетплейса в разделе «Маркетплейсы».",
        "Попробуйте запустить синхронизацию вручную.",
        "Если ошибка повторяется — обратитесь в службу поддержки.",
    ]


# ── Stream card rendering ────────────────────────────────────────────────────

def _stream_card(item: dict) -> str:
    sync_key = item["sync_key"]
    title = item["title"]
    status = item["status"]
    badge_cls, badge_label = STATUS_BADGE.get(status, ("pending", "Ожидает запуска"))
    icon = item["icon"]
    has_wb = item["has_wb"]
    has_ozon = item["has_ozon"]
    last_run = item["last_run"]
    last_success = item["last_success"]
    duration = item["duration"]
    records = item["records"]
    last_error = item["last_error"]
    trigger_key = item["trigger_key"]
    is_running = status == "running"

    wb_cls = "" if has_wb else " inactive"
    ozon_cls = "" if has_ozon else " inactive"
    wb_title = "Wildberries подключён" if has_wb else "Wildberries не подключён"
    ozon_title = "Ozon подключён" if has_ozon else "Ozon не подключён"

    # Error snippet
    if last_error and status == "error":
        short_err = (last_error[:180] + "…") if len(last_error) > 180 else last_error
        error_html = f"""
        <div class="sd-stream-error">
          <div class="sd-stream-error-title">Последняя ошибка:</div>
          {escape(short_err)}
        </div>"""
    else:
        error_html = ""

    # Extra meta chips
    extra_meta = ""
    if records is not None and records > 0:
        extra_meta += f"""
        <div class="sd-time-item">
          <span class="sd-time-label">Обработано</span>
          <span class="sd-time-value">{records:,} зап.</span>
        </div>"""
    if duration != "н/д":
        extra_meta += f"""
        <div class="sd-time-item">
          <span class="sd-time-label">Длительность</span>
          <span class="sd-time-value">{escape(duration)}</span>
        </div>"""

    # Run button
    if is_running:
        run_btn = '<button class="sd-btn sd-btn-primary" disabled>Выполняется…</button>'
    elif trigger_key:
        run_btn = f'<button class="sd-btn sd-btn-primary" onclick="sdRunSync(this, {json.dumps(trigger_key)})">Запустить</button>'
    else:
        run_btn = (
            '<button class="sd-btn sd-btn-primary" disabled '
            'title="Ручной запуск для этого типа данных не поддерживается">'
            'Запустить</button>'
        )

    # Diagnostics data embedded in attribute
    diag_data = {
        "title": title,
        "status": status,
        "last_run_at": last_run,
        "last_success_at": last_success,
        "duration": duration,
        "records": str(records) if records is not None else None,
        "last_error": last_error,
        "recommendations": item["recommendations"],
    }
    diag_json = escape(json.dumps(diag_data, ensure_ascii=False))

    return f"""
    <div class="sd-stream" data-status="{escape(badge_cls)}" data-title="{escape(title.lower())}" data-key="{escape(sync_key)}" data-diag="{diag_json}">
      <div class="sd-stream-icon">{icon}</div>
      <div class="sd-stream-body">
        <div class="sd-stream-header">
          <div class="sd-stream-title">{escape(title)}</div>
          <span class="sd-badge {badge_cls}">{escape(badge_label)}</span>
        </div>
        <div class="sd-stream-desc">{escape(item["description"])}</div>
        <div class="sd-stream-meta">
          <div class="sd-stream-mp">
            <span class="sd-mp-badge wb{wb_cls}" title="{escape(wb_title)}">WB</span>
            <span class="sd-mp-badge ozon{ozon_cls}" title="{escape(ozon_title)}">Ozon</span>
          </div>
          <div class="sd-stream-times">
            <div class="sd-time-item">
              <span class="sd-time-label">Последний запуск</span>
              <span class="sd-time-value">{escape(last_run)}</span>
            </div>
            <div class="sd-time-item">
              <span class="sd-time-label">Последний успех</span>
              <span class="sd-time-value">{escape(last_success)}</span>
            </div>
            {extra_meta}
          </div>
        </div>
        {error_html}
      </div>
      <div class="sd-stream-actions">
        {run_btn}
        <button class="sd-btn sd-btn-ghost" onclick="sdOpenHistory({json.dumps(sync_key)}, {json.dumps(title)})">История</button>
        <button class="sd-btn sd-btn-ghost" onclick="sdOpenDiagByKey({json.dumps(sync_key)})">Диагностика</button>
      </div>
    </div>"""


# ── CSS ──────────────────────────────────────────────────────────────────────

def _sd_css() -> str:
    return """<style>
/* ── Sync Dashboard ─────────────────────────────────── */

/* Hero */
.sd-hero {
  background: linear-gradient(135deg, var(--accent-bg, #eff6ff) 0%, var(--bg-card, #fff) 100%);
  border: 1px solid var(--border-light, #edf2f7);
  border-radius: var(--radius-xl, 18px);
  padding: 28px 32px;
  margin-bottom: 20px;
}
.sd-hero-content {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 24px;
  flex-wrap: wrap;
}
.sd-hero-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--text, #0b1a33);
  margin: 0 0 8px;
}
.sd-hero-desc {
  font-size: 14px;
  color: var(--text-secondary, #475569);
  margin: 0;
  max-width: 540px;
  line-height: 1.6;
}
.sd-hero-meta { display: flex; gap: 14px; flex-wrap: wrap; }
.sd-meta-item {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #fff;
  border: 1px solid var(--border, #e2e8f0);
  border-radius: var(--radius-lg, 14px);
  padding: 10px 16px;
  min-width: 148px;
}
.sd-meta-icon { font-size: 20px; line-height: 1; }
.sd-meta-label { font-size: 11px; color: var(--text-muted, #94a3b8); font-weight: 500; }
.sd-meta-value { font-size: 14px; color: var(--text, #0b1a33); font-weight: 600; margin-top: 2px; }

/* Stats grid */
.sd-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
.sd-stat {
  background: #fff;
  border: 1px solid var(--border, #e2e8f0);
  border-radius: var(--radius-lg, 14px);
  padding: 20px 24px;
  text-align: center;
  box-shadow: var(--shadow-xs, 0 1px 2px rgba(15,23,42,.04));
}
.sd-stat-num {
  font-size: 34px;
  font-weight: 700;
  color: var(--text, #0b1a33);
  line-height: 1;
  margin-bottom: 6px;
}
.sd-stat-lbl { font-size: 13px; color: var(--text-secondary, #475569); }
.sd-stat.success .sd-stat-num { color: var(--success, #059669); }
.sd-stat.error .sd-stat-num   { color: var(--danger, #dc2626); }
.sd-stat.pending .sd-stat-num { color: var(--warning, #d97706); }

/* Error alert */
.sd-alert {
  background: var(--danger-soft, #fef2f2);
  border: 1px solid var(--danger-border, #fecaca);
  border-radius: var(--radius-lg, 14px);
  padding: 18px 20px;
  margin-bottom: 20px;
}
.sd-alert-title { font-weight: 600; color: var(--danger, #dc2626); margin-bottom: 14px; font-size: 14px; }
.sd-alert-item {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 12px 14px;
  background: #fff;
  border-radius: var(--radius, 10px);
  margin-bottom: 8px;
  border: 1px solid var(--danger-border, #fecaca);
  gap: 12px;
}
.sd-alert-item:last-child { margin-bottom: 0; }
.sd-alert-item-title { font-weight: 600; font-size: 13px; color: var(--text, #0b1a33); }
.sd-alert-item-msg   { font-size: 12px; color: var(--danger, #dc2626); margin-top: 3px; word-break: break-word; }
.sd-alert-item-time  { font-size: 11px; color: var(--text-muted, #94a3b8); white-space: nowrap; }

/* Toolbar */
.sd-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.sd-filters { display: flex; gap: 6px; flex-wrap: wrap; }
.sd-filter {
  padding: 7px 16px;
  border: 1px solid var(--border, #e2e8f0);
  border-radius: 999px;
  background: #fff;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  color: var(--text-secondary, #475569);
  transition: all .15s;
  line-height: 1;
}
.sd-filter:hover { border-color: var(--accent, #2563eb); color: var(--accent, #2563eb); }
.sd-filter.active { background: var(--accent, #2563eb); border-color: var(--accent, #2563eb); color: #fff; }
.sd-search-wrap { position: relative; flex: 1; min-width: 180px; max-width: 300px; }
.sd-search {
  width: 100%;
  padding: 8px 14px;
  border: 1px solid var(--border, #e2e8f0);
  border-radius: 999px;
  font-size: 13px;
  background: #fff;
  outline: none;
  transition: border-color .15s, box-shadow .15s;
}
.sd-search:focus {
  border-color: var(--accent, #2563eb);
  box-shadow: 0 0 0 3px var(--accent-soft, #dbeafe);
}

/* Stream cards */
.sd-streams { display: flex; flex-direction: column; gap: 12px; margin-bottom: 24px; }
.sd-stream {
  background: #fff;
  border: 1px solid var(--border, #e2e8f0);
  border-radius: var(--radius-lg, 14px);
  padding: 20px 24px;
  display: flex;
  gap: 18px;
  align-items: flex-start;
  box-shadow: var(--shadow-xs, 0 1px 2px rgba(15,23,42,.04));
  transition: box-shadow .15s;
}
.sd-stream:hover { box-shadow: var(--shadow-sm, 0 1px 3px rgba(15,23,42,.05)); }
.sd-stream.sd-hidden { display: none; }
.sd-stream-icon {
  font-size: 26px;
  width: 46px;
  height: 46px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-muted, #f1f4f9);
  border-radius: var(--radius, 10px);
  flex-shrink: 0;
}
.sd-stream-body { flex: 1; min-width: 0; }
.sd-stream-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 5px;
  flex-wrap: wrap;
}
.sd-stream-title { font-size: 15px; font-weight: 600; color: var(--text, #0b1a33); }
.sd-stream-desc  { font-size: 13px; color: var(--text-secondary, #475569); margin-bottom: 12px; line-height: 1.5; }
.sd-stream-meta  { display: flex; gap: 18px; flex-wrap: wrap; align-items: flex-start; }
.sd-stream-mp    { display: flex; gap: 6px; align-items: center; padding-top: 2px; }
.sd-mp-badge {
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .03em;
}
.sd-mp-badge.wb   { background: var(--wb-soft, #f5f3ff); color: var(--wb, #7c3aed); border: 1px solid var(--wb-border, #ddd6fe); }
.sd-mp-badge.ozon { background: var(--ozon-soft, #eff6ff); color: var(--ozon, #2563eb); border: 1px solid var(--ozon-border, #bfdbfe); }
.sd-mp-badge.inactive { opacity: .4; }
.sd-stream-times { display: flex; gap: 18px; flex-wrap: wrap; }
.sd-time-item { display: flex; flex-direction: column; gap: 2px; }
.sd-time-label {
  font-size: 10px;
  color: var(--text-muted, #94a3b8);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .05em;
}
.sd-time-value { font-size: 13px; color: var(--text, #0b1a33); font-weight: 500; }
.sd-stream-error {
  margin-top: 10px;
  padding: 10px 14px;
  background: var(--danger-soft, #fef2f2);
  border: 1px solid var(--danger-border, #fecaca);
  border-radius: var(--radius, 10px);
  font-size: 12px;
  color: var(--danger, #dc2626);
  word-break: break-word;
  line-height: 1.5;
}
.sd-stream-error-title { font-weight: 600; margin-bottom: 3px; }
.sd-stream-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
  min-width: 120px;
}

/* Badges */
.sd-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
}
.sd-badge.success { background: var(--success-soft, #ecfdf5); color: var(--success, #059669); border: 1px solid var(--success-border, #a7f3d0); }
.sd-badge.error   { background: var(--danger-soft, #fef2f2);  color: var(--danger, #dc2626);   border: 1px solid var(--danger-border, #fecaca); }
.sd-badge.warning { background: #ffedd5; color: #9a3412; border: 1px solid #fed7aa; }
.sd-badge.running { background: var(--info-soft, #eff6ff); color: var(--info, #2563eb); border: 1px solid var(--info-border, #bfdbfe); }
.sd-badge.pending { background: var(--warning-soft, #fffbeb); color: var(--warning, #d97706); border: 1px solid var(--warning-border, #fde68a); }
.sd-badge.disabled{ background: #f1f5f9; color: #64748b; border: 1px solid #e2e8f0; }
@keyframes sd-pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
.sd-badge.running::before {
  content: '';
  display: inline-block;
  width: 7px; height: 7px;
  background: currentColor;
  border-radius: 50%;
  animation: sd-pulse 1.2s ease-in-out infinite;
}

/* Buttons */
.sd-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: var(--radius, 10px);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all .15s;
  border: 1px solid transparent;
  white-space: nowrap;
  width: 100%;
  line-height: 1;
}
.sd-btn-primary { background: var(--accent, #2563eb); color: #fff; border-color: var(--accent, #2563eb); }
.sd-btn-primary:hover:not(:disabled) { background: var(--accent-hover, #1d4ed8); }
.sd-btn-ghost { background: transparent; color: var(--text-secondary, #475569); border-color: var(--border, #e2e8f0); }
.sd-btn-ghost:hover { background: var(--bg-muted, #f1f4f9); color: var(--text, #0b1a33); }
.sd-btn:disabled { opacity: .5; cursor: not-allowed; }
.sd-btn-sm { padding: 5px 10px; font-size: 12px; width: auto; }

/* Schedule block */
.sd-schedule, .sd-help {
  background: #fff;
  border: 1px solid var(--border, #e2e8f0);
  border-radius: var(--radius-lg, 14px);
  padding: 24px;
  margin-bottom: 20px;
  box-shadow: var(--shadow-xs, 0 1px 2px rgba(15,23,42,.04));
}
.sd-help { background: var(--bg-muted, #f1f4f9); }
.sd-section-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text, #0b1a33);
  margin: 0 0 18px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.sd-schedule-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
}
.sd-schedule-item {
  padding: 14px 16px;
  background: var(--bg-muted, #f1f4f9);
  border-radius: var(--radius, 10px);
  border: 1px solid var(--border-light, #edf2f7);
}
.sd-schedule-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .05em;
  color: var(--text-muted, #94a3b8);
  margin-bottom: 4px;
}
.sd-schedule-value { font-size: 14px; font-weight: 600; color: var(--text, #0b1a33); }

/* Help */
.sd-help-items {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
  margin-top: 14px;
}
.sd-help-item {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 12px 14px;
  background: #fff;
  border-radius: var(--radius, 10px);
  border: 1px solid var(--border, #e2e8f0);
}
.sd-help-icon { font-size: 18px; flex-shrink: 0; margin-top: 1px; }
.sd-help-text { font-size: 13px; color: var(--text-secondary, #475569); line-height: 1.55; }

/* Modal */
.sd-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(11,26,51,.45);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  opacity: 0;
  pointer-events: none;
  transition: opacity .2s;
}
.sd-modal-overlay.sd-open { opacity: 1; pointer-events: all; }
.sd-modal {
  background: #fff;
  border-radius: var(--radius-xl, 18px);
  box-shadow: var(--shadow-lg, 0 20px 30px -8px rgba(15,23,42,.08));
  width: 100%;
  max-width: 760px;
  max-height: 82vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transform: translateY(16px);
  transition: transform .2s;
}
.sd-modal-overlay.sd-open .sd-modal { transform: translateY(0); }
.sd-modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px 24px;
  border-bottom: 1px solid var(--border, #e2e8f0);
  flex-shrink: 0;
}
.sd-modal-title { font-size: 16px; font-weight: 600; color: var(--text, #0b1a33); margin: 0; }
.sd-modal-close {
  background: none;
  border: none;
  font-size: 18px;
  cursor: pointer;
  color: var(--text-muted, #94a3b8);
  padding: 4px 6px;
  border-radius: var(--radius-sm, 6px);
  line-height: 1;
  transition: background .15s;
}
.sd-modal-close:hover { background: var(--bg-muted, #f1f4f9); color: var(--text, #0b1a33); }
.sd-modal-body { overflow-y: auto; padding: 24px; flex: 1; }

/* History table */
.sd-history-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.sd-history-table th {
  text-align: left;
  padding: 8px 10px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .05em;
  color: var(--text-muted, #94a3b8);
  border-bottom: 1px solid var(--border, #e2e8f0);
}
.sd-history-table td {
  padding: 10px;
  border-bottom: 1px solid var(--border-light, #edf2f7);
  vertical-align: top;
  color: var(--text, #0b1a33);
}
.sd-history-table tr:last-child td { border-bottom: none; }
.sd-loading { text-align: center; padding: 40px; color: var(--text-muted, #94a3b8); font-size: 14px; }

/* Diagnostics */
.sd-diag-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}
.sd-diag-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .05em;
  color: var(--text-muted, #94a3b8);
  margin-bottom: 4px;
}
.sd-diag-value { font-size: 14px; color: var(--text, #0b1a33); font-weight: 500; word-break: break-word; }
.sd-diag-error {
  background: var(--danger-soft, #fef2f2);
  border: 1px solid var(--danger-border, #fecaca);
  border-radius: var(--radius, 10px);
  padding: 12px 14px;
  font-size: 12px;
  color: var(--danger, #dc2626);
  margin: 14px 0;
  word-break: break-word;
  max-height: 140px;
  overflow-y: auto;
  line-height: 1.5;
}
.sd-diag-recs {
  background: var(--info-soft, #eff6ff);
  border: 1px solid var(--info-border, #bfdbfe);
  border-radius: var(--radius, 10px);
  padding: 14px 16px;
}
.sd-diag-recs-title { font-weight: 600; color: var(--info, #2563eb); margin-bottom: 10px; font-size: 13px; }
.sd-diag-rec {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 13px;
  color: var(--text-secondary, #475569);
  line-height: 1.5;
}
.sd-diag-rec:last-child { margin-bottom: 0; }
.sd-diag-rec::before { content: '→'; color: var(--accent, #2563eb); flex-shrink: 0; font-weight: 600; }

/* Responsive */
@media (max-width: 1024px) {
  .sd-stats { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 768px) {
  .sd-hero { padding: 18px 20px; }
  .sd-hero-content { flex-direction: column; }
  .sd-hero-meta { width: 100%; }
  .sd-meta-item { flex: 1; min-width: 130px; }
  .sd-stats { grid-template-columns: repeat(2, 1fr); gap: 12px; }
  .sd-stream { flex-direction: column; gap: 14px; }
  .sd-stream-actions { flex-direction: row; width: 100%; }
  .sd-btn { flex: 1; }
  .sd-toolbar { flex-direction: column; align-items: stretch; }
  .sd-search-wrap { max-width: none; }
  .sd-diag-grid { grid-template-columns: 1fr; }
  .sd-modal { border-radius: var(--radius-lg, 14px); }
}
@media (max-width: 480px) {
  .sd-stats { gap: 10px; }
  .sd-stat { padding: 16px 12px; }
  .sd-stat-num { font-size: 28px; }
  .sd-stream { padding: 14px 16px; }
  .sd-schedule-grid { grid-template-columns: 1fr 1fr; }
}
</style>"""


# ── JS ───────────────────────────────────────────────────────────────────────

def _sd_js() -> str:
    return """<script>
(function () {
'use strict';

/* ── Filter & Search ── */
var filterBtns = document.querySelectorAll('.sd-filter');
var streams = document.querySelectorAll('.sd-stream');
var searchInput = document.getElementById('sdSearch');
var activeFilter = 'all';
var activeSearch = '';

function applyFilters() {
  streams.forEach(function (el) {
    var status = el.dataset.status || '';
    var title  = el.dataset.title  || '';
    var matchFilter =
      activeFilter === 'all' ||
      (activeFilter === 'success' && status === 'success') ||
      (activeFilter === 'error'   && status === 'error') ||
      (activeFilter === 'pending' && (status === 'pending' || status === 'waiting'));
    var matchSearch = !activeSearch || title.indexOf(activeSearch) !== -1;
    el.classList.toggle('sd-hidden', !(matchFilter && matchSearch));
  });
}

filterBtns.forEach(function (btn) {
  btn.addEventListener('click', function () {
    filterBtns.forEach(function (b) { b.classList.remove('active'); });
    btn.classList.add('active');
    activeFilter = btn.dataset.filter || 'all';
    applyFilters();
  });
});

if (searchInput) {
  searchInput.addEventListener('input', function () {
    activeSearch = searchInput.value.trim().toLowerCase();
    applyFilters();
  });
}

/* ── Modal helpers ── */
var historyOverlay = document.getElementById('sdHistoryModal');
var diagOverlay    = document.getElementById('sdDiagModal');

function openModal(el)  { if (el) el.classList.add('sd-open'); }
function closeModal(el) { if (el) el.classList.remove('sd-open'); }

[historyOverlay, diagOverlay].forEach(function (ov) {
  if (!ov) return;
  ov.addEventListener('click', function (e) {
    if (e.target === ov) closeModal(ov);
  });
});

document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') { closeModal(historyOverlay); closeModal(diagOverlay); }
});

window.sdCloseHistory = function () { closeModal(historyOverlay); };
window.sdCloseDiag    = function () { closeModal(diagOverlay); };

/* ── History modal ── */
var STATUS_LABELS = {
  queued: 'В очереди', running: 'Выполняется', success: 'Успешно',
  error: 'Ошибка', warning: 'Предупреждение', timeout: 'Таймаут',
  cancelled: 'Отменено', failed: 'Ошибка'
};

window.sdOpenHistory = function (syncKey, title) {
  var body   = document.getElementById('sdHistoryBody');
  var titleEl = document.getElementById('sdHistoryTitle');
  if (titleEl) titleEl.textContent = 'История: ' + title;
  if (body) body.innerHTML = '<div class="sd-loading">Загрузка данных…</div>';
  openModal(historyOverlay);

  fetch('/web/settings/sync/history?sync_key=' + encodeURIComponent(syncKey), {
    headers: { Accept: 'application/json' }
  })
  .then(function (r) { return r.json(); })
  .then(function (data) {
    if (!data.ok || !data.runs || !data.runs.length) {
      body.innerHTML = '<div class="sd-loading">Запусков для этого типа синхронизации пока нет.</div>';
      return;
    }
    var rows = data.runs.map(function (r) {
      var sc = r.status === 'success' ? 'success' : r.status === 'error' || r.status === 'failed' ? 'error' : 'pending';
      var lbl = STATUS_LABELS[r.status] || r.status;
      var started = r.started_at ? new Date(r.started_at).toLocaleString('ru') : '—';
      var dur = r.duration_seconds != null
        ? (r.duration_seconds < 60 ? Math.round(r.duration_seconds) + ' сек' : Math.round(r.duration_seconds / 60) + ' мин')
        : '—';
      var mp = r.marketplace || '—';
      var rec = r.records_loaded || 0;
      var err = r.error_message
        ? '<span style="color:var(--danger,#dc2626);font-size:11px">' + esc(r.error_message.slice(0, 150)) + '</span>'
        : '—';
      return '<tr>' +
        '<td>' + esc(started) + '</td>' +
        '<td><span class="sd-badge ' + sc + '">' + esc(lbl) + '</span></td>' +
        '<td><span class="sd-mp-badge ' + mp.toLowerCase() + '">' + esc(mp) + '</span></td>' +
        '<td>' + rec + '</td>' +
        '<td>' + esc(dur) + '</td>' +
        '<td>' + err + '</td>' +
        '</tr>';
    }).join('');
    body.innerHTML =
      '<table class="sd-history-table"><thead><tr>' +
      '<th>Дата запуска</th><th>Статус</th><th>МП</th><th>Записей</th><th>Длительность</th><th>Ошибка</th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table>';
  })
  .catch(function () {
    body.innerHTML = '<div class="sd-loading">Не удалось загрузить данные.</div>';
  });
};

/* ── Diagnostics modal ── */
function sdDiagItem(label, value) {
  return '<div><div class="sd-diag-label">' + esc(label) + '</div><div class="sd-diag-value">' + value + '</div></div>';
}

function sdOpenDiagFromData(item) {
  var titleEl = document.getElementById('sdDiagTitle');
  var body    = document.getElementById('sdDiagBody');
  if (!item || !body) return;
  if (titleEl) titleEl.textContent = 'Диагностика: ' + (item.title || '');

  var LABELS = { success:'Успешно', error:'Ошибка', pending:'Ожидает запуска', running:'Выполняется', warning:'Предупреждения', skipped:'Пропущено', disabled:'Отключено' };
  var sc  = item.status || 'pending';
  var lbl = LABELS[sc] || sc;

  var recs = Array.isArray(item.recommendations) ? item.recommendations : [];
  var recsHtml = recs.map(function (r) {
    return '<div class="sd-diag-rec">' + esc(r) + '</div>';
  }).join('') || '<div class="sd-diag-rec">Проблем не обнаружено.</div>';

  var errHtml = item.last_error
    ? '<div class="sd-diag-label" style="margin-top:12px">Последняя ошибка</div><div class="sd-diag-error">' + esc(item.last_error) + '</div>'
    : '';

  body.innerHTML =
    '<div class="sd-diag-grid">' +
    sdDiagItem('Тип синхронизации', esc(item.title || '—')) +
    sdDiagItem('Статус', '<span class="sd-badge ' + sc + '">' + esc(lbl) + '</span>') +
    sdDiagItem('Последний запуск', esc(item.last_run_at || 'Пока не запускалось')) +
    sdDiagItem('Последний успех',  esc(item.last_success_at || 'Нет данных')) +
    sdDiagItem('Обработано записей', esc(item.records || '—')) +
    sdDiagItem('Длительность', esc(item.duration || '—')) +
    '</div>' +
    errHtml +
    '<div class="sd-diag-recs"><div class="sd-diag-recs-title">Рекомендации</div>' + recsHtml + '</div>';

  openModal(diagOverlay);
}

window.sdOpenDiag = function (jsonStr) {
  try { sdOpenDiagFromData(typeof jsonStr === 'string' ? JSON.parse(jsonStr) : jsonStr); }
  catch (e) { console.error('sdOpenDiag parse error', e); }
};

window.sdOpenDiagByKey = function (syncKey) {
  var el = document.querySelector('[data-key="' + syncKey + '"]');
  if (!el) return;
  try { sdOpenDiagFromData(JSON.parse(el.dataset.diag || '{}')); }
  catch (e) { console.error('sdOpenDiagByKey parse error', e); }
};

/* ── Manual sync trigger ── */
window.sdRunSync = function (btn, triggerKey) {
  if (!triggerKey) return;
  var orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Запускаю…';

  fetch('/web/settings/sync/run/' + encodeURIComponent(triggerKey), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' }
  })
  .then(function (r) { return r.json(); })
  .then(function (data) {
    if (data.ok) {
      btn.textContent = 'Запущено!';
      sdToast(data.message || 'Синхронизация поставлена в очередь', 'success');
      setTimeout(function () { btn.textContent = orig; btn.disabled = false; }, 3500);
    } else {
      btn.textContent = orig;
      btn.disabled = false;
      sdToast(data.message || 'Не удалось запустить синхронизацию', 'error');
    }
  })
  .catch(function () {
    btn.textContent = orig;
    btn.disabled = false;
    sdToast('Ошибка соединения. Попробуйте позже.', 'error');
  });
};

/* ── Toast notification ── */
function sdToast(msg, type) {
  var t = document.createElement('div');
  var ok = type === 'success';
  t.style.cssText = [
    'position:fixed;bottom:22px;right:22px;padding:12px 18px',
    'border-radius:10px;font-size:13px;font-weight:500;z-index:9999',
    'box-shadow:0 4px 14px rgba(0,0,0,.12);transition:opacity .3s',
    'max-width:360px;word-break:break-word;line-height:1.5',
    ok ? 'background:#dcfce7;color:#166534;border:1px solid #bbf7d0'
       : 'background:#fee2e2;color:#991b1b;border:1px solid #fca5a5'
  ].join(';');
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(function () {
    t.style.opacity = '0';
    setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 320);
  }, 4000);
}

/* ── Escape HTML ── */
function esc(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}

})();
</script>"""


# ── Main view function ───────────────────────────────────────────────────────

def _sync_tab(
    sync_statuses: list[Any],
    timezone: str,
    tabs_html: str = "",
    accounts: list[Any] | None = None,
    subscription_data: Any | None = None,
) -> str:
    """Render the Настройки → Синхронизация tab — professional sync dashboard."""

    accounts = accounts or []

    # Connectivity flags
    try:
        from app.models.enums import Marketplace
        has_wb   = any(getattr(a, "marketplace", None) == Marketplace.WB   for a in accounts)
        has_ozon = any(getattr(a, "marketplace", None) == Marketplace.OZON for a in accounts)
    except Exception:
        has_wb = has_ozon = bool(accounts)

    # Statistics
    total         = len(sync_statuses)
    success_count = sum(1 for s in sync_statuses if getattr(s, "status", "") == "success")
    error_count   = sum(1 for s in sync_statuses if getattr(s, "status", "") == "error")
    pending_count = sum(1 for s in sync_statuses if getattr(s, "status", "") == "pending")
    running_count = sum(1 for s in sync_statuses if getattr(s, "status", "") == "running")

    # Last activity
    run_times = [getattr(s, "last_run_at", None) for s in sync_statuses if getattr(s, "last_run_at", None)]
    last_activity = _fmt_dt(max(run_times) if run_times else None, timezone)

    # Tier / schedule info
    tier_name = "Free"
    sync_interval_minutes = 180
    if subscription_data is not None:
        tier = getattr(subscription_data, "tier", None)
        if tier:
            tier_name = getattr(tier, "name", "Free") or "Free"
            sync_interval_minutes = int(getattr(tier, "sync_interval_minutes", 180) or 180)
    sync_interval_label = _fmt_interval(sync_interval_minutes)

    # Build item dicts for rendering
    items: list[dict] = []
    for s in sync_statuses:
        sync_key = getattr(s, "sync_type", "")
        status   = getattr(s, "status", "pending")
        error    = getattr(s, "last_error_message", None)
        items.append({
            "sync_key":    sync_key,
            "title":       getattr(s, "sync_type_label", sync_key),
            "description": SYNC_DESCRIPTIONS.get(sync_key, "Синхронизация данных"),
            "icon":        SYNC_ICONS.get(sync_key, "🔄"),
            "status":      status,
            "has_wb":      has_wb,
            "has_ozon":    has_ozon,
            "last_run":    _fmt_dt(getattr(s, "last_run_at", None), timezone),
            "last_success":_fmt_dt(getattr(s, "last_success_at", None), timezone),
            "duration":    _fmt_duration(getattr(s, "duration_seconds", None)),
            "records":     getattr(s, "items_processed", None),
            "last_error":  error,
            "trigger_key": SYNC_TRIGGER_KEYS.get(sync_key),
            "recommendations": _recommendations(status, error),
        })

    # Error alert block
    error_items = [i for i in items if i["status"] == "error"]
    error_alert_html = ""
    if error_items:
        rows_html = ""
        for item in error_items[:3]:
            raw_msg = item["last_error"] or "Неизвестная ошибка"
            short_msg = (raw_msg[:140] + "…") if len(raw_msg) > 140 else raw_msg
            rows_html += f"""
            <div class="sd-alert-item">
              <div style="flex:1;min-width:0">
                <div class="sd-alert-item-title">{escape(item["title"])}</div>
                <div class="sd-alert-item-msg">{escape(short_msg)}</div>
              </div>
              <div style="flex-shrink:0;text-align:right">
                <div class="sd-alert-item-time">{escape(item["last_run"])}</div>
                <button class="sd-btn sd-btn-ghost sd-btn-sm" style="margin-top:6px"
                        onclick="sdOpenDiagByKey({json.dumps(item['sync_key'])})">Диагностика</button>
              </div>
            </div>"""
        plural = "а" if error_count == 1 else ("и" if 1 < error_count < 5 else "")
        error_alert_html = f"""
        <div class="sd-alert">
          <div class="sd-alert-title">⚠️ Требуют внимания — {error_count} ошибк{plural}</div>
          {rows_html}
        </div>"""

    # Stream cards
    stream_cards = "\n".join(_stream_card(item) for item in items)

    # Schedule block
    wb_status   = "Подключён" if has_wb   else "Не подключён"
    ozon_status = "Подключён" if has_ozon else "Не подключён"
    schedule_html = f"""
    <div class="sd-schedule">
      <h2 class="sd-section-title">📅 Расписание синхронизации</h2>
      <div class="sd-schedule-grid">
        <div class="sd-schedule-item">
          <div class="sd-schedule-label">Текущий тариф</div>
          <div class="sd-schedule-value">{escape(tier_name)}</div>
        </div>
        <div class="sd-schedule-item">
          <div class="sd-schedule-label">Автосинхронизация</div>
          <div class="sd-schedule-value">{escape(sync_interval_label)}</div>
        </div>
        <div class="sd-schedule-item">
          <div class="sd-schedule-label">Кабинетов</div>
          <div class="sd-schedule-value">{len(accounts)}</div>
        </div>
        <div class="sd-schedule-item">
          <div class="sd-schedule-label">Wildberries</div>
          <div class="sd-schedule-value">{wb_status}</div>
        </div>
        <div class="sd-schedule-item">
          <div class="sd-schedule-label">Ozon</div>
          <div class="sd-schedule-value">{ozon_status}</div>
        </div>
        <div class="sd-schedule-item">
          <div class="sd-schedule-label">Ручной запуск</div>
          <div class="sd-schedule-value">Доступен</div>
        </div>
      </div>
      <p style="margin:16px 0 0;font-size:13px;color:var(--text-secondary,#475569)">
        Ручной запуск синхронизации также доступен через
        <a href="/web/sync-center">Центр синхронизации</a> или Telegram-бота.
      </p>
    </div>"""

    # Help block
    help_html = """
    <div class="sd-help">
      <h2 class="sd-section-title">💡 Что делать, если синхронизация не работает?</h2>
      <div class="sd-help-items">
        <div class="sd-help-item">
          <span class="sd-help-icon">🔑</span>
          <div class="sd-help-text">Проверьте, что API-ключ маркетплейса активен. Перейдите в <a href="/web/settings?tab=marketplaces">«Маркетплейсы»</a>.</div>
        </div>
        <div class="sd-help-item">
          <span class="sd-help-icon">🔗</span>
          <div class="sd-help-text">Убедитесь, что кабинет маркетплейса подключён и имеет статус «Активен».</div>
        </div>
        <div class="sd-help-item">
          <span class="sd-help-icon">🔄</span>
          <div class="sd-help-text">Попробуйте запустить синхронизацию вручную, нажав кнопку «Запустить» в карточке потока.</div>
        </div>
        <div class="sd-help-item">
          <span class="sd-help-icon">🔍</span>
          <div class="sd-help-text">Нажмите «Диагностика» — там отображается полная информация об ошибке и рекомендации.</div>
        </div>
        <div class="sd-help-item">
          <span class="sd-help-icon">📊</span>
          <div class="sd-help-text">В «Истории» показаны все прошлые попытки синхронизации с деталями и причинами ошибок.</div>
        </div>
        <div class="sd-help-item">
          <span class="sd-help-icon">💬</span>
          <div class="sd-help-text">Если ошибка повторяется — обратитесь в поддержку через <a href="/web/settings?tab=support">«Поддержку»</a>.</div>
        </div>
      </div>
    </div>"""

    # Modals
    modals_html = """
    <div class="sd-modal-overlay" id="sdHistoryModal" role="dialog" aria-modal="true" aria-labelledby="sdHistoryTitle">
      <div class="sd-modal">
        <div class="sd-modal-header">
          <h3 class="sd-modal-title" id="sdHistoryTitle">История запусков</h3>
          <button class="sd-modal-close" onclick="sdCloseHistory()" aria-label="Закрыть">✕</button>
        </div>
        <div class="sd-modal-body" id="sdHistoryBody">
          <div class="sd-loading">Загрузка…</div>
        </div>
      </div>
    </div>

    <div class="sd-modal-overlay" id="sdDiagModal" role="dialog" aria-modal="true" aria-labelledby="sdDiagTitle">
      <div class="sd-modal">
        <div class="sd-modal-header">
          <h3 class="sd-modal-title" id="sdDiagTitle">Диагностика</h3>
          <button class="sd-modal-close" onclick="sdCloseDiag()" aria-label="Закрыть">✕</button>
        </div>
        <div class="sd-modal-body" id="sdDiagBody"></div>
      </div>
    </div>"""

    # Activity summary
    active_str  = str(running_count) if running_count else "Нет"
    error_str   = str(error_count)   if error_count   else "Нет"

    return f"""\
{_sd_css()}
{tabs_html}

<div class="sd-hero">
  <div class="sd-hero-content">
    <div class="sd-hero-text">
      <h1 class="sd-hero-title">Синхронизация данных</h1>
      <p class="sd-hero-desc">Контролируйте загрузку заказов, продаж, остатков, цен, финансовых отчётов и других данных из Wildberries и Ozon.</p>
    </div>
    <div class="sd-hero-meta">
      <div class="sd-meta-item">
        <span class="sd-meta-icon">🕐</span>
        <div>
          <div class="sd-meta-label">Последняя активность</div>
          <div class="sd-meta-value">{escape(last_activity)}</div>
        </div>
      </div>
      <div class="sd-meta-item">
        <span class="sd-meta-icon">⚡</span>
        <div>
          <div class="sd-meta-label">Активных задач</div>
          <div class="sd-meta-value">{escape(active_str)}</div>
        </div>
      </div>
      <div class="sd-meta-item">
        <span class="sd-meta-icon">⚠️</span>
        <div>
          <div class="sd-meta-label">Ошибок</div>
          <div class="sd-meta-value">{escape(error_str)}</div>
        </div>
      </div>
    </div>
  </div>
</div>

<div class="sd-stats">
  <div class="sd-stat">
    <div class="sd-stat-num">{total}</div>
    <div class="sd-stat-lbl">Всего потоков данных</div>
  </div>
  <div class="sd-stat success">
    <div class="sd-stat-num">{success_count}</div>
    <div class="sd-stat-lbl">Работают стабильно</div>
  </div>
  <div class="sd-stat error">
    <div class="sd-stat-num">{error_count}</div>
    <div class="sd-stat-lbl">Требуют внимания</div>
  </div>
  <div class="sd-stat pending">
    <div class="sd-stat-num">{pending_count}</div>
    <div class="sd-stat-lbl">Ожидают запуска</div>
  </div>
</div>

{error_alert_html}

<div class="sd-toolbar">
  <div class="sd-filters">
    <button class="sd-filter active" data-filter="all">Все</button>
    <button class="sd-filter" data-filter="success">Работают</button>
    <button class="sd-filter" data-filter="error">Ошибки</button>
    <button class="sd-filter" data-filter="pending">Ожидают</button>
  </div>
  <div class="sd-search-wrap">
    <input class="sd-search" id="sdSearch" type="search" placeholder="Поиск по типу данных…">
  </div>
</div>

<div class="sd-streams" id="sdStreams">
{stream_cards}
</div>

{schedule_html}

{help_html}

{modals_html}

{_sd_js()}
"""
