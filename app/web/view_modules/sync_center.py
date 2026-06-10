"""version: 2.0.0
description: Sync Center HTML view with account cards, freshness, run history, errors, settings.
updated: 2026-06-10
"""

# ruff: noqa: E501

import json
from datetime import datetime
from decimal import Decimal
from html import escape

from app.models.domain import SyncRun
from app.services.account.web_cabinet_service import SyncCenterPageData
from app.services.common.sync_period_limits import ManualSyncPeriodLimits
from app.services.common.web_sync_run_service import SYNC_TYPE_MAP
from app.web.view_modules.common import _sync_center_subnav
from app.web.view_modules.formatting import _marketplace_label, _rub

ZERO = Decimal("0")


def _sync_center_content(
    data: SyncCenterPageData,
    is_admin: bool = False,
    limits: ManualSyncPeriodLimits | None = None,
    period_supported: list[str] | None = None,
) -> str:
    healthy_pct = round(data.healthy_accounts / data.total_accounts * 100) if data.total_accounts else 0
    healthy_tone = "good" if healthy_pct >= 80 else ("warn" if healthy_pct >= 50 else "bad")
    dq_tone = _tone_for_score(data.data_quality_score)
    stale_count = sum(
        1 for a in data.accounts
        if a.sync_freshness_orders in ("bad", "none")
    )
    error_count = data.error_accounts_count
    last_success = _last_success_time(data.accounts)

    last_sync_display = last_success.strftime("%d.%m.%Y %H:%M") if last_success else "нет данных"

    account_cards_html = "".join(
        _account_card(acc_data, is_admin) for acc_data in data.accounts
    ) if data.accounts else (
        '<div class="empty-state"><strong>Нет подключённых кабинетов</strong><span>Добавьте кабинет Wildberries или Ozon в разделе «Кабинеты МП».</span></div>'
    )

    period_bar = _sync_period_bar(limits, period_supported) if limits else ""
    limits_json = ""
    if limits:
        limits_json = json.dumps({
            "max_days_back": limits.max_days_back,
            "max_range_days": limits.max_range_days,
            "tariff_code": limits.tariff_code,
            "tariff_name": limits.tariff_name,
            "period_supported": period_supported or [],
        })

    return f"""
    {_sync_center_subnav("overview")}
    <div class="page-header">
      <div>
        <h2>Центр синхронизации</h2>
        <p style="margin:4px 0 0;color:var(--text-muted);font-size:13px">Контроль загрузки данных Wildberries и Ozon, ручной запуск синхронизаций и диагностика ошибок.</p>
      </div>
      <div class="page-actions">
        <button class="btn btn-sm" onclick="location.reload()" title="Обновить данные страницы">🔄 Обновить</button>
        <button class="btn btn-sm btn-primary" onclick="retryAllStale()" id="retryAllBtn" title="Повторить все просроченные">↻ Повторить просроченные</button>
        { '<button class="btn btn-sm btn-danger" onclick="retryAllErrors()" id="retryAllErrorsBtn" title="Повторить все ошибки">↻ Повторить ошибки</button>' if is_admin else '' }
      </div>
    </div>
    {period_bar}
    <div class="premium-kpi-grid">
      <div class="premium-kpi good"><span>Кабинетов подключено</span><strong>{data.total_accounts}</strong><small>всего кабинетов</small></div>
      <div class="premium-kpi {healthy_tone}"><span>Здоровье</span><strong>{healthy_pct}%</strong><small>{data.healthy_accounts} из {data.total_accounts} без ошибок</small></div>
      <div class="premium-kpi neutral"><span>Товаров</span><strong>{data.total_products}</strong><small>всего товаров</small></div>
      <div class="premium-kpi action"><span>Заказов за 30 дней</span><strong>{data.total_orders_30d}</strong><small>за последние 30 дней</small></div>
      <div class="premium-kpi {'bad' if error_count > 0 else 'good'}"><span>С ошибками</span><strong>{error_count}</strong><small>{'требуют внимания' if error_count > 0 else 'ошибок нет'}</small></div>
      <div class="premium-kpi {'bad' if stale_count > 0 else 'good'}"><span>Просрочено</span><strong>{stale_count}</strong><small>синхронизаций с просрочкой</small></div>
      <div class="premium-kpi {dq_tone}"><span>Качество данных</span><strong>{data.data_quality_score or 'н/д'}{'%' if data.data_quality_score is not None else ''}</strong><small>оценка качества</small></div>
      <div class="premium-kpi"><span>Последняя синхронизация</span><span style="font-size:14px">{last_sync_display}</span><small>успешная синхронизация</small></div>
    </div>
    {account_cards_html}
    <script id="sync-period-limits-data" type="application/json">{limits_json}</script>
    """


def _account_card(acc_data: object, is_admin: bool) -> str:
    a = acc_data.account
    is_ozon = a.marketplace.value == "OZON"

    status_badge = _account_status(a)
    api_badge = _api_key_status_badge(a)
    balance = _rub(acc_data.balance.current) if acc_data.balance and acc_data.balance.current is not None else "н/д"
    last_sync = a.last_success_sync_at.strftime("%d.%m.%Y %H:%M") if a.last_success_sync_at else "никогда"
    last_error = a.last_error_message or ""

    btns = _sync_buttons(a, is_ozon)
    freshness = _freshness_table(acc_data, is_ozon)
    error_block = _error_block(a)

    return f"""
    <section class="premium-section" style="margin-bottom:14px" data-account-id="{a.id}" data-marketplace="{a.marketplace.value}">
      <div class="section-head">
        <div>
          <h2 style="margin-bottom:2px">{escape(a.name or 'Кабинет')}</h2>
          <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:4px">
            {_marketplace_label(a.marketplace)}
            <span class="muted">{escape(a.seller_external_id or '')}</span>
            {status_badge}
            {api_badge}
          </div>
        </div>
      </div>

      <div class="mini-stat-grid" style="margin-bottom:12px">
        <div class="mini-stat"><span>Товаров</span><strong>{acc_data.products_count}</strong></div>
        <div class="mini-stat"><span>Заказы за 30д</span><strong>{acc_data.orders_30d}</strong></div>
        <div class="mini-stat"><span>Баланс</span><strong>{balance}</strong></div>
        <div class="mini-stat"><span>Последняя синхронизация</span><strong style="font-size:12px">{last_sync}</strong></div>
        <div class="mini-stat"><span>Статус кабинета</span><strong>{escape(a.status.value)}</strong></div>
        <div class="mini-stat"><span>Проверка ключа</span><strong style="font-size:12px">{a.api_key_checked_at.strftime('%d.%m.%Y %H:%M') if a.api_key_checked_at else 'не проверялся'}</strong></div>
      </div>

      {error_block}

      <div style="margin-bottom:10px">
        {btns}
      </div>

      <details style="margin-top:6px">
        <summary class="button-tiny" style="cursor:pointer;display:inline-flex">📊 Свежесть данных</summary>
        <div style="margin-top:8px">
          {freshness}
        </div>
      </details>
    </section>
    """


def _sync_buttons(account: object, is_ozon: bool) -> str:
    aid = account.id
    mp = account.marketplace.value
    is_active = account.is_active
    api_ok = account.api_key_status == "valid"

    disabled = ""
    disabled_title = ""
    if not is_active:
        disabled = ' disabled'
        disabled_title = ' title="Кабинет отключён"'
    elif not api_ok:
        disabled = ' disabled'
        disabled_title = ' title="API-ключ не проверен"'

    def _btn(sync_type: str, label: str, extra_cls: str = "", title: str = "") -> str:
        nonlocal disabled, disabled_title
        title_attr = f' title="{escape(title)}"' if title else ""
        return f'<button class="btn btn-sm {extra_cls}" data-account-id="{aid}" data-sync-type="{sync_type}" data-marketplace="{mp}" data-running="false"{disabled}{disabled_title}{title_attr}>{label}</button>'

    def _wbtn(sync_type: str, label: str, title: str = "") -> str:
        return _btn(sync_type, label, title=title)

    btns = [
        _btn("all", "↻ Синхронизировать всё", "btn-primary"),
        _btn("products", "📦 Товары"),
        _btn("stocks", "📊 Остатки"),
    ]

    if not is_ozon:
        btns.extend([
            _wbtn("wb_orders_stats", "📋 Заказы WB", "Загружает заказы из статистики WB. Доступны за последние 90 дней."),
            _wbtn("orders", "📋 Сборочные задания FBS", "Загружает FBS-сборочные задания, а не все заказы."),
            _wbtn("sales", "💰 Продажи"),
            _wbtn("returns", "↩ Возвраты"),
            _wbtn("wb_reports", "📑 Отчёты WB"),
            _wbtn("wb_financial_details", "📊 Финансовые детализации WB"),
            _wbtn("profile", "👤 Профиль"),
            _wbtn("finances", "💳 Финансы"),
            _wbtn("logistics", "🚚 Логистика WB"),
        ])
    else:
        btns.extend([
            _wbtn("orders", "📋 Заказы"),
            _wbtn("sales", "💰 Продажи"),
            _wbtn("returns", "↩ Возвраты"),
            _wbtn("profile", "👤 Профиль"),
            _wbtn("finances", "💳 Финансы"),
            _wbtn("ozon_finances", "💳 Финансы Ozon"),
            _wbtn("ozon_balance", "⚖ Баланс Ozon"),
        ])

    btns.extend([
        f'<button class="btn btn-sm" data-account-id="{aid}" data-verify-key="true"{"" if is_active else " disabled"}>🔑 Проверить API-ключ</button>',
        f'<a class="btn btn-sm" href="/web/sync-center?tab=history&account_id={aid}">📜 История</a>',
        f'<a class="btn btn-sm" href="/web/sync-center?tab=errors&account_id={aid}">⚠ Ошибки</a>',
    ])

    return '<div class="sync-btn-grid">' + "".join(btns) + "</div>"


def _freshness_table(acc_data: object, is_ozon: bool) -> str:
    if is_ozon:
        entries = [
            ("sync_freshness_orders", "Заказы", "orders"),
            ("sync_freshness_sales", "Продажи", "sales"),
            ("sync_freshness_stocks", "Остатки", "stocks"),
            ("sync_freshness_products", "Товары", "products"),
            ("sync_freshness_profile", "Профиль", "profile"),
            ("sync_freshness_ozon_finance", "Финансы Ozon", "ozon_finances"),
        ]
    else:
        entries = [
            ("sync_freshness_orders", "Сборочные задания FBS", "orders"),
            ("sync_freshness_orders", "Заказы WB", "wb_orders_stats"),
            ("sync_freshness_sales", "Продажи", "sales"),
            ("sync_freshness_stocks", "Остатки", "stocks"),
            ("sync_freshness_products", "Товары", "products"),
            ("sync_freshness_profile", "Профиль", "profile"),
            ("sync_freshness_wb_reports", "Отчёты WB", "wb_reports"),
            ("sync_freshness_wb_financial_details", "Фин. детализации WB", "wb_financial_details"),
        ]

    tones = {"good": "good", "warn": "warn", "bad": "bad", "none": ""}
    labels = {"good": "OK", "warn": "Задержка", "bad": "Просрочка", "none": "Нет данных"}

    rows_html = ""
    for attr, label, sync_type in entries:
        val = getattr(acc_data, attr, "none")
        tone = tones.get(val, "")
        label_text = labels.get(val, val)

        ts = _sync_ts(acc_data.account, sync_type)
        last_ts = ts.strftime("%d.%m.%Y %H:%M") if ts else "—"
        next_run = _next_run(sync_type)

        rows_html += f"""
        <tr>
          <td><strong>{label}</strong></td>
          <td>{last_ts}</td>
          <td><span class="badge {tone}">{label_text}</span></td>
          <td class="muted">{next_run}</td>
          <td>
            <button class="button-tiny" data-account-id="{acc_data.account.id}" data-sync-type="{sync_type}" data-marketplace="{acc_data.account.marketplace.value}">Запустить</button>
          </td>
        </tr>"""

    return f"""
    <div class="table-wrap">
      <table class="table" style="font-size:12px">
        <thead>
          <tr>
            <th>Тип данных</th>
            <th>Последнее обновление</th>
            <th>Статус</th>
            <th>Следующий запуск</th>
            <th>Действия</th>
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
    </div>"""


def _sync_ts(account: object, sync_type: str) -> datetime | None:
    mapping = {
        "orders": "last_order_poll_at",
        "wb_orders_stats": "last_orders_sync_at",
        "wb_fbs_assembly_orders": "last_order_poll_at",
        "sales": "last_sales_sync_at",
        "stocks": "last_stocks_sync_at",
        "products": "last_products_sync_at",
        "profile": "last_profile_sync_at",
        "wb_reports": "last_wb_reports_sync_at",
        "wb_financial_details": "last_wb_financial_detail_sync_at",
        "ozon_finances": "last_ozon_finance_sync_at",
    }
    attr = mapping.get(sync_type)
    if attr is None:
        return None
    return getattr(account, attr, None)


def _next_run(sync_type: str) -> str:
    intervals = {
        "orders": "каждые 3 мин",
        "wb_orders_stats": "вручную",
        "wb_fbs_assembly_orders": "вручную",
        "sales": "каждые 15 мин",
        "stocks": "3 раза в день",
        "products": "каждый час",
        "profile": "2 раза в день",
        "wb_reports": "раз в день",
        "wb_financial_details": "раз в день",
        "ozon_finances": "3 раза в день",
        "finances": "раз в день",
        "logistics": "раз в день",
        "returns": "каждые 15 мин",
    }
    return intervals.get(sync_type, "автоматически")


def _account_status(account: object) -> str:
    if not account.is_active:
        return '<span class="badge warn">Отключён</span>'
    mapping = {
        "ERROR": ("bad", "Ошибка"),
        "ACTIVE": ("good", "Активен"),
        "DRAFT": ("", "Черновик"),
        "DISABLED": ("warn", "Отключён"),
    }
    tone, label = mapping.get(account.status.value, ("", account.status.value))
    return f'<span class="badge {tone}">{label}</span>'


def _api_key_status_badge(account: object) -> str:
    mapping = {
        "valid": ("good", "Ключ проверен"),
        "invalid": ("bad", "Ошибка ключа"),
        "unchecked": ("warn", "Ключ не проверен"),
    }
    tone, label = mapping.get(account.api_key_status or "unchecked", ("warn", "Ключ не проверен"))
    return f'<span class="badge {tone}">{label}</span>'


def _error_block(account: object) -> str:
    if not account.last_error_message:
        return ""
    msg = escape(str(account.last_error_message)[:300])
    when = account.last_error_at.strftime("%d.%m.%Y %H:%M") if account.last_error_at else ""
    return f"""
    <div class="notice danger" style="margin-bottom:10px">
      <strong>⚠ Ошибка синхронизации</strong>
      {f'<span class="muted" style="float:right">{when}</span>' if when else ''}
      <div style="margin-top:4px;font-size:12px">{msg}</div>
    </div>"""


def _sync_center_history_content(runs: list[SyncRun], is_admin: bool) -> str:
    has_running = any(r.status == "running" for r in runs)
    if not runs:
        rows_html = '<tr><td colspan="12"><div class="empty-state compact">История запусков пуста.</div></td></tr>'
    else:
        rows_html = ""
        for r in runs:
            dur = f"{float(r.duration_seconds):.1f} сек" if r.duration_seconds else "—"
            started = r.started_at.strftime("%d.%m.%Y %H:%M") if r.started_at else "—"
            rows_html += f"""
            <tr>
              <td>{started}</td>
              <td>{escape(r.marketplace)}</td>
              <td>{_sync_type_label(r.sync_type)}</td>
              <td>{_trigger_source_label(r.trigger_source)}</td>
              <td>{_period_display(r)}</td>
              <td>{_run_status_badge(r.status)}</td>
              <td>{dur}</td>
              <td class="num">{r.records_loaded}</td>
              <td class="num">{r.records_created}</td>
              <td class="num">{r.records_updated}</td>
              <td class="num">{r.records_skipped}</td>
              <td><span class="muted">{escape(r.error_message[:100]) if r.error_message else '—'}</span></td>
            </tr>"""

    auto_refresh_script = ""
    if has_running:
        auto_refresh_script = """
        <script>
          (function() {
            if (window._syncHistoryRefresh) return;
            window._syncHistoryRefresh = true;
            var count = 0;
            var interval = setInterval(function() {
              count++;
              if (count >= 30) { clearInterval(interval); return; }
              fetch('/web/sync-center/history?limit=100&t=' + Date.now())
                .then(function(r) { return r.json(); })
                .then(function(data) {
                  if (!data.runs) return;
                  var stillRunning = data.runs.some(function(run) { return run.status === 'running'; });
                  if (!stillRunning) { clearInterval(interval); }
                  location.reload();
                })
                .catch(function() {});
            }, 15000);
          })();
        </script>"""

    return f"""
    {_sync_center_subnav("history")}
    {auto_refresh_script}
    <div class="page-header">
      <div>
        <h2>История запусков</h2>
        <p class="muted">Все ручные и автоматические запуски синхронизаций.</p>
      </div>
      <div class="page-actions">
        <button class="btn btn-sm" onclick="location.reload()">🔄 Обновить</button>
      </div>
    </div>
    <div class="table-card">
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Дата и время</th>
              <th>Маркетплейс</th>
              <th>Тип синхронизации</th>
              <th>Источник</th>
              <th>Период</th>
              <th>Статус</th>
              <th>Длительность</th>
              <th class="num">Загружено</th>
              <th class="num">Создано</th>
              <th class="num">Обновлено</th>
              <th class="num">Пропущено</th>
              <th>Ошибка</th>
            </tr>
          </thead>
          <tbody>{rows_html}</tbody>
        </table>
      </div>
    </div>"""


def _sync_center_errors_content(runs: list[SyncRun], is_admin: bool) -> str:
    if not runs:
        items_html = '<div class="empty-state"><strong>Ошибок нет</strong><span>Все синхронизации работают штатно.</span></div>'
    else:
        items = ""
        for r in runs:
            when = r.created_at.strftime("%d.%m.%Y %H:%M") if r.created_at else "—"
            tech = f"<div class='mono' style='margin-top:6px;font-size:11px'>{escape(r.error_message)}</div>" if (is_admin and r.error_message) else ""
            retry_btn = f'<button class="button-tiny" data-account-id="{r.marketplace_account_id}" data-sync-type="{r.sync_type}" data-marketplace="{r.marketplace}">↻ Повторить</button>'

            items += f"""
            <div class="attention-item bad">
              <div>
                <strong>{_sync_type_label(r.sync_type)} — {escape(r.marketplace)}</strong>
                <div class="event-meta">
                  <span class="badge bad">Ошибка</span>
                  <span class="muted">{when}</span>
                  <span class="muted">попыток: 1</span>
                </div>
                <p style="margin-top:4px">
                  {_human_error(r.error_message) if r.error_message else 'Произошла неизвестная ошибка.'}
                </p>
                {tech}
              </div>
              <div style="display:flex;gap:4px">
                {retry_btn}
              </div>
            </div>"""

        items_html = f'<div class="attention-list">{items}</div>'

    return f"""
    {_sync_center_subnav("errors")}
    <div class="page-header">
      <div>
        <h2>Ошибки синхронизации</h2>
        <p class="muted">Диагностика и повтор проблемных синхронизаций.</p>
      </div>
      <div class="page-actions">
        <button class="btn btn-sm" onclick="location.reload()">🔄 Обновить</button>
        {'<button class="btn btn-sm btn-danger" onclick="retryAllErrors()">↻ Повторить все</button>' if is_admin else ''}
      </div>
    </div>
    {items_html}"""


def _sync_center_settings_content() -> str:
    return f"""
    {_sync_center_subnav("settings")}
    <div class="page-header">
      <div>
        <h2>Настройки автообновления</h2>
        <p class="muted">Расписание фоновых синхронизаций.</p>
      </div>
    </div>
    <div class="band">
      <table class="table">
        <thead>
          <tr><th>Тип синхронизации</th><th>Частота</th><th>Статус</th></tr>
        </thead>
        <tbody>
          <tr><td>Сборочные задания FBS</td><td>Каждые 3 минуты</td><td><span class="badge good">Активно</span></td></tr>
          <tr><td>Продажи и возвраты</td><td>Каждые 15 минут</td><td><span class="badge good">Активно</span></td></tr>
          <tr><td>Остатки</td><td>3 раза в день (8:00, 14:00, 20:00)</td><td><span class="badge good">Активно</span></td></tr>
          <tr><td>Товары</td><td>Каждый час</td><td><span class="badge good">Активно</span></td></tr>
          <tr><td>Профиль кабинета</td><td>2 раза в день</td><td><span class="badge good">Активно</span></td></tr>
          <tr><td>Финансовые отчёты WB</td><td>Раз в день (5:00)</td><td><span class="badge good">Активно</span></td></tr>
          <tr><td>Финансовые детализации WB</td><td>Раз в день (5:00)</td><td><span class="badge good">Активно</span></td></tr>
          <tr><td>Финансы Ozon</td><td>3 раза в день</td><td><span class="badge good">Активно</span></td></tr>
          <tr><td>Акции WB</td><td>Каждые 30 минут</td><td><span class="badge good">Активно</span></td></tr>
          <tr><td>Тарифы логистики WB</td><td>Раз в день</td><td><span class="badge good">Активно</span></td></tr>
        </tbody>
      </table>
      <div class="notice" style="margin-top:12px">
        <strong>Информация</strong><br>
        Настройки автообновления управляются системой. Ручное изменение расписания будет добавлено позже.
      </div>
    </div>"""


def _sync_period_bar(limits: ManualSyncPeriodLimits, period_supported: list[str] | None) -> str:
    limit_hint = f"Ваш тариф: макс. {limits.max_days_back} дн. глубины, макс. {limits.max_range_days} дн. диапазона."
    preset_buttons = ""
    for days in (7, 30, 90, 180, 365):
        if days <= limits.max_days_back:
            preset_buttons += f'<button class="button-tiny" data-preset="{days}d">{days} дн.</button>'
    return f"""
    <div class="sync-period-bar" style="margin-bottom:14px;padding:10px 14px;border:1px solid var(--border);border-radius:var(--radius);background:var(--bg-card)">
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;margin-bottom:0">
        <input type="checkbox" id="sync-period-toggle" onchange="toggleSyncPeriod(this.checked)"> 📅 <strong>Период синхронизации</strong>
        <span class="muted" style="font-size:12px;margin-left:8px">{limit_hint}</span>
      </label>
      <div id="sync-period-controls" style="display:none;margin-top:10px;padding-top:10px;border-top:1px solid var(--border)">
        <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:8px">
          <span class="muted" style="font-size:12px">Быстрый выбор:</span>
          {preset_buttons}
          <button class="button-tiny active" data-preset="custom" onclick="selectSyncPeriodPreset('custom')">Свой</button>
        </div>
        <div id="sync-period-custom" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <label style="font-size:12px">с <input type="date" id="sync-period-from" style="font-size:12px;padding:2px 6px"></label>
          <label style="font-size:12px">по <input type="date" id="sync-period-to" style="font-size:12px;padding:2px 6px"></label>
          <button class="button-tiny" onclick="applySyncPeriod()">Применить</button>
          <button class="button-tiny" onclick="clearSyncPeriod()">Сбросить</button>
        </div>
        <div id="sync-period-active" style="display:none;margin-top:6px;font-size:12px">
          <span class="badge action" id="sync-period-badge">Период не выбран</span>
        </div>
      </div>
    </div>"""


def _period_display(run: SyncRun) -> str:
    details = run.details_json
    if not details:
        return '<span class="muted">—</span>'
    source_api = details.get("source_api", "")
    if not details.get("date_from"):
        if source_api:
            return f'<span class="muted" style="font-size:10px">{escape(source_api)}</span>'
        return '<span class="muted">—</span>'
    date_from = details["date_from"]
    date_to = details["date_to"]
    period_days = details.get("period_days", 0)
    api_hint = f" {escape(source_api)}" if source_api else ""
    return f'<span class="muted" style="font-size:11px" title="{escape(date_from)} → {escape(date_to)}{api_hint}">{date_from} – {date_to} ({period_days} дн.)</span>'


def _tone_for_score(score: int | None) -> str:
    if score is None:
        return ""
    if score >= 80:
        return "good"
    if score >= 50:
        return "warn"
    return "bad"


def _last_success_time(accounts: list) -> datetime | None:
    candidates = []
    for a in accounts:
        acc = a.account
        for field in (
            "last_order_poll_at", "last_sales_sync_at", "last_stocks_sync_at",
            "last_products_sync_at", "last_profile_sync_at",
            "last_wb_reports_sync_at", "last_ozon_finance_sync_at",
            "last_orders_sync_at", "last_wb_financial_detail_sync_at",
        ):
            ts = getattr(acc, field, None)
            if ts is not None:
                candidates.append(ts)
    return max(candidates) if candidates else None


def _run_status_badge(status: str) -> str:
    mapping = {
        "queued": ("action", "В очереди"),
        "running": ("action", "Выполняется"),
        "success": ("good", "Успешно"),
        "warning": ("warn", "Предупреждение"),
        "error": ("bad", "Ошибка"),
        "failed": ("bad", "Ошибка"),
        "timeout": ("bad", "Превышено время"),
        "cancelled": ("", "Отменено"),
        "pending": ("", "Ожидает"),
    }
    tone, label = mapping.get(status, ("", status))
    return f'<span class="badge {tone}">{label}</span>'


def _trigger_source_label(source: str) -> str:
    mapping = {
        "manual": "Вручную",
        "auto": "Автоматически",
        "automatic": "Автоматически",
        "cron": "Автоматически",
        "scheduler": "Автоматически",
        "system": "Система",
        "web_admin": "Админ",
    }
    return mapping.get(source, source)


def _sync_type_label(sync_type: str) -> str:
    info = SYNC_TYPE_MAP.get(sync_type, {})
    return info.get("label", sync_type)


def _human_error(error: str | None) -> str:
    if not error:
        return "Произошла неизвестная ошибка."
    error_lower = error.lower()
    if "timeout" in error_lower:
        return "Сервер маркетплейса не ответил вовремя. Задача будет автоматически повторена при следующем запуске. Можно запустить повтор вручную."
    if "empty" in error_lower or "пуст" in error_lower:
        return "Маркетплейс вернул пустой ответ. Данные не обновлены. Задача будет автоматически повторена при следующем запуске."
    if "401" in error_lower or "403" in error_lower or "unauthorized" in error_lower or "forbidden" in error_lower:
        return "Ошибка авторизации API. Проверьте API-ключ в настройках кабинета."
    if "429" in error_lower or "too many" in error_lower:
        return "Превышен лимит запросов к API маркетплейса. Задача будет повторена автоматически."
    if "500" in error_lower or "502" in error_lower or "503" in error_lower:
        return "Сервер маркетплейса временно недоступен. Задача будет повторена автоматически."
    if "connection" in error_lower or "dns" in error_lower:
        return "Ошибка сетевого подключения к API маркетплейса. Проверьте соединение."
    if "rate limit" in error_lower:
        return "Достигнут лимит запросов. Задача будет повторена автоматически."
    return f"Техническая ошибка: {error[:200]}"
