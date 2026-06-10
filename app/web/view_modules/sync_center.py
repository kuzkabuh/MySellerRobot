"""version: 1.0.0
description: Sync Center HTML view helpers for user-facing sync health dashboard.
updated: 2026-06-09
"""

# ruff: noqa: E501

from decimal import Decimal
from html import escape

from app.services.account.web_cabinet_service import SyncCenterPageData
from app.web.view_modules.common import _section_subnav_monitoring
from app.web.view_modules.formatting import _marketplace_label, _rub

ZERO = Decimal("0")


def _sync_center_content(data: SyncCenterPageData) -> str:
    account_cards = []
    for acc_data in data.accounts:
        a = acc_data.account
        status_badge = _account_status_badge(a.status.value, a.is_active)
        freshness_rows = _sync_freshness_rows(acc_data, a.marketplace.value == "OZON")
        api_key_status = _api_key_badge(a.api_key_status)
        last_sync = (
            f"{a.last_success_sync_at.strftime('%d.%m.%Y %H:%M')}" if a.last_success_sync_at else "никогда"
        )
        last_error = (
            f'<div class="error-text">{escape(str(a.last_error_message)[:200])}</div>'
            if a.last_error_message
            else ""
        )
        balance = _rub(acc_data.balance.current) if acc_data.balance and acc_data.balance.current is not None else "н/д"
        account_cards.append(
            f"""
        <section class="band" style="margin-top:14px">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
            <div>
              <h2 style="margin:0">{escape(a.name or 'Кабинет')}</h2>
              <div class="muted">{_marketplace_label(a.marketplace)} · {escape(a.seller_external_id or '')}</div>
            </div>
            <div style="display:flex;gap:8px;align-items:center">
              {status_badge} {api_key_status}
            </div>
          </div>
          <div class="kv" style="margin-top:10px">
            <span>Товаров</span><strong>{acc_data.products_count}</strong>
            <span>Заказов за 30д</span><strong>{acc_data.orders_30d}</strong>
            <span>Баланс</span><strong>{balance}</strong>
            <span>Последняя синхронизация</span><strong>{last_sync}</strong>
          </div>
          {last_error}
          <div style="margin-top:10px">
            <h3 style="margin:0 0 6px 0;font-size:14px">Свежесть синхронизации</h3>
            <div class="table-wrap">
              <table class="table" style="font-size:13px">
                <thead>
                  <tr>
                    <th>Заказы</th><th>Продажи</th><th>Остатки</th><th>Товары</th>
                    <th>Профиль</th><th>{"Финансы Ozon" if a.marketplace.value == "OZON" else "Отчёты WB"}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    {freshness_rows}
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>
        """
        )
    accounts_html = "".join(account_cards) if account_cards else (
        '<div class="empty-state">Нет подключённых кабинетов маркетплейсов.</div>'
    )

    healthy_pct = round(data.healthy_accounts / data.total_accounts * 100) if data.total_accounts else 0
    healthy_tone = "good" if healthy_pct >= 80 else ("warn" if healthy_pct >= 50 else "bad")
    stale_tone = "bad" if data.stale_accounts > 0 else "good"
    dq_tone = "good" if data.data_quality_score and data.data_quality_score >= 80 else (
        "warn" if data.data_quality_score and data.data_quality_score >= 50 else "bad"
    ) if data.data_quality_score is not None else ""

    return f"""
      {_section_subnav_monitoring("sync")}
      <section class="kpi-grid">
        <div class="kpi"><span class="kpi-value">{data.total_accounts}</span><span class="kpi-label">Кабинетов</span></div>
        <div class="kpi"><span class="kpi-value">{_kpi_value(healthy_pct, "%")}</span><span class="kpi-label healthy {healthy_tone}">Здоровье</span></div>
        <div class="kpi"><span class="kpi-value">{data.total_products}</span><span class="kpi-label">Товаров</span></div>
        <div class="kpi"><span class="kpi-value">{data.total_orders_30d}</span><span class="kpi-label">Заказов за 30д</span></div>
        <div class="kpi"><span class="kpi-value">{data.error_accounts_count}</span><span class="kpi-label errors {stale_tone}">С ошибками</span></div>
        <div class="kpi"><span class="kpi-value">{data.stale_accounts}</span><span class="kpi-label stale {stale_tone}">Просрочка</span></div>
      </section>
      <section class="kpi-grid">
        <div class="kpi"><span class="kpi-value">{_kpi_value(data.data_quality_score, "")}</span><span class="kpi-label quality {dq_tone}">Качество данных</span></div>
      </section>
      {accounts_html}
    """


def _account_status_badge(status: str, is_active: bool) -> str:
    if status == "ERROR":
        tone = "bad"
        label = "Ошибка"
    elif status == "DISABLED":
        tone = "warn"
        label = "Отключён"
    elif not is_active:
        tone = "warn"
        label = "Неактивен"
    elif status == "ACTIVE":
        tone = "good"
        label = "Активен"
    else:
        tone = "warn"
        label = "Черновик"
    return f'<span class="badge {tone}">{label}</span>'


def _api_key_badge(api_status: str | None) -> str:
    mapping = {
        "valid": ("good", "Ключ OK"),
        "invalid": ("bad", "Ключ недействителен"),
        "unchecked": ("warn", "Ключ не проверен"),
    }
    tone, label = mapping.get(api_status or "unchecked", ("warn", "Ключ не проверен"))
    return f'<span class="badge {tone}">{label}</span>'


def _sync_freshness_rows(acc_data: object, is_ozon: bool = False) -> str:
    entries = [
        ("sync_freshness_orders", "Заказы"),
        ("sync_freshness_sales", "Продажи"),
        ("sync_freshness_stocks", "Остатки"),
        ("sync_freshness_products", "Товары"),
        ("sync_freshness_profile", "Профиль"),
    ]
    if is_ozon:
        entries.append(("sync_freshness_ozon_finance", "Финансы Ozon"))
    else:
        entries.append(("sync_freshness_wb_reports", "Отчёты WB"))
    tones = {"good": "good", "warn": "warn", "bad": "bad", "none": ""}
    labels = {"good": "OK", "warn": "Задержка", "bad": "Просрочка", "none": "Нет данных"}
    cells = []
    for attr, _ in entries:
        val = getattr(acc_data, attr, "none")
        tone = tones.get(val, "")
        label = labels.get(val, val)
        cells.append(f'<td class="num"><span class="badge {tone}">{label}</span></td>')
    return "".join(cells)


def _kpi_value(value: int | None, suffix: str) -> str:
    if value is None:
        return "н/д"
    return f"{value}{suffix}"
