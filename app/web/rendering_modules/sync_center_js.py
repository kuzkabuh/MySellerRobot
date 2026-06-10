"""JavaScript for Sync Center: auto-refresh, run sync, verify API key, toasts, period selector."""

SYNC_CENTER_JS = """
(function() {
  var pollingIntervals = {};
  var syncPeriodActive = false;
  var syncPeriodFrom = null;
  var syncPeriodTo = null;
  var syncPeriodPreset = null;
  var syncPeriodDays = null;

  var SYNC_PERIOD_SUPPORTED = [];
  try {
    var limitsEl = document.getElementById('sync-period-limits-data');
    if (limitsEl) {
      var limitsData = JSON.parse(limitsEl.textContent);
      SYNC_PERIOD_SUPPORTED = limitsData.period_supported || [];
    }
  } catch(e) {}

  function showToast(message, type) {
    type = type || 'info';
    var container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      document.body.appendChild(container);
    }
    var toast = document.createElement('div');
    toast.className = 'toast ' + type;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(function() {
      toast.style.animation = 'toast-out 0.3s ease-in forwards';
      setTimeout(function() { toast.remove(); }, 300);
    }, 4000);
  }

  window.toggleSyncPeriod = function(checked) {
    var controls = document.getElementById('sync-period-controls');
    if (controls) { controls.style.display = checked ? 'block' : 'none'; }
    if (!checked) { clearSyncPeriod(); }
  };

  window.selectSyncPeriodPreset = function(preset) {
    document.querySelectorAll('[data-preset]').forEach(function(btn) {
      btn.classList.toggle('active', btn.getAttribute('data-preset') === preset);
    });
    var custom = document.getElementById('sync-period-custom');
    if (custom) { custom.style.display = preset === 'custom' ? 'flex' : 'none'; }
    if (preset !== 'custom') {
      syncPeriodPreset = preset;
      syncPeriodDays = parseInt(preset.replace('d', ''), 10);
      syncPeriodFrom = null;
      syncPeriodTo = null;
      updateSyncPeriodBadge();
    }
  };

  window.applySyncPeriod = function() {
    var fromEl = document.getElementById('sync-period-from');
    var toEl = document.getElementById('sync-period-to');
    if (!fromEl || !toEl) return;
    var fromVal = fromEl.value;
    var toVal = toEl.value;
    if (!fromVal || !toVal) {
      showToast('Укажите даты начала и окончания периода.', 'warn');
      return;
    }
    if (fromVal > toVal) {
      showToast('Дата начала не может быть позже даты окончания.', 'error');
      return;
    }
    syncPeriodFrom = fromVal;
    syncPeriodTo = toVal;
    syncPeriodPreset = 'custom';
    syncPeriodDays = Math.round((new Date(toVal) - new Date(fromVal)) / (1000 * 60 * 60 * 24));
    document.querySelectorAll('[data-preset]').forEach(function(btn) {
      btn.classList.toggle('active', btn.getAttribute('data-preset') === 'custom');
    });
    updateSyncPeriodBadge();
    showToast('Период синхронизации установлен: ' + fromVal + ' — ' + toVal, 'success');
  };

  window.clearSyncPeriod = function() {
    syncPeriodActive = false;
    syncPeriodFrom = null;
    syncPeriodTo = null;
    syncPeriodPreset = null;
    syncPeriodDays = null;
    document.querySelectorAll('[data-preset]').forEach(function(btn) {
      btn.classList.remove('active');
    });
    var badge = document.getElementById('sync-period-badge');
    if (badge) { badge.textContent = 'Период не выбран'; badge.className = 'badge'; }
    var activeDiv = document.getElementById('sync-period-active');
    if (activeDiv) { activeDiv.style.display = 'none'; }
    var fromEl = document.getElementById('sync-period-from');
    var toEl = document.getElementById('sync-period-to');
    if (fromEl) fromEl.value = '';
    if (toEl) toEl.value = '';
  };

  function updateSyncPeriodBadge() {
    var badge = document.getElementById('sync-period-badge');
    var activeDiv = document.getElementById('sync-period-active');
    if (!badge || !activeDiv) return;
    activeDiv.style.display = 'block';
    syncPeriodActive = true;
    if (syncPeriodFrom && syncPeriodTo) {
      badge.textContent = 'Период: ' + syncPeriodFrom + ' — ' + syncPeriodTo + ' (' + syncPeriodDays + ' дн.)';
    } else if (syncPeriodPreset) {
      badge.textContent = 'Период: последние ' + syncPeriodDays + ' дней';
    }
    badge.className = 'badge action';
  }

  function getPeriodParams() {
    if (!syncPeriodActive) return '';
    if (syncPeriodFrom && syncPeriodTo) {
      return '&date_from=' + encodeURIComponent(syncPeriodFrom) + '&date_to=' + encodeURIComponent(syncPeriodTo);
    }
    if (syncPeriodPreset && syncPeriodPreset !== 'custom') {
      return '&period_preset=' + encodeURIComponent(syncPeriodPreset);
    }
    return '';
  }

    function isPeriodSupported(syncType) {
      return SYNC_PERIOD_SUPPORTED.indexOf(syncType) >= 0;
    }

    function triggerSync(accountId, syncType, marketplace, btn) {
      if (btn && (btn.disabled || btn.classList.contains('running'))) return;

      if (syncType === 'all') {
        if (!confirm('Запустить синхронизацию всех типов данных для этого кабинета?')) return;
        if (marketplace === 'WB') {
          var syncTypes = ['products', 'stocks', 'wb_orders_stats', 'orders', 'sales', 'returns', 'wb_reports', 'wb_financial_details', 'profile', 'finances', 'logistics'];
        } else {
          var syncTypes = ['products', 'stocks', 'orders', 'sales', 'returns', 'profile', 'finances', 'ozon_finances'];
        }
      syncTypes.forEach(function(st) {
        triggerSingleSync(accountId, st, marketplace, null);
      });
      showToast('Синхронизации запускаются...', 'info');
      return;
    }

    triggerSingleSync(accountId, syncType, marketplace, btn);
  }

  function triggerSingleSync(accountId, syncType, marketplace, btn) {
    if (btn && btn instanceof HTMLElement) {
      btn.disabled = true;
      btn.classList.add('running');
      btn.textContent = 'Выполняется...';
    }

    var url = '/web/sync-center/accounts/' + accountId + '/run?sync_type=' + encodeURIComponent(syncType);
    if (isPeriodSupported(syncType)) {
      url += getPeriodParams();
    }

    fetch(url, { method: 'POST', headers: { 'x-forwarded-for': window.location.host } })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.already_running) {
          showToast(data.message || 'Уже выполняется', 'info');
          if (btn) { resetBtn(btn); }
          if (data.run_id) {
            pollRunStatus(data.run_id, btn);
          }
        } else if (data.ok) {
          showToast(data.message || 'Синхронизация запущена', 'success');
          if (data.run_id) {
            pollRunStatus(data.run_id, btn);
          } else if (btn) {
            btn.textContent = 'Запущен';
            setTimeout(function() { resetBtn(btn); }, 3000);
          }
        } else {
          var msg = data.message || 'Ошибка запуска';
          showToast(msg, 'error');
          if (btn) { resetBtn(btn); }
        }
      })
      .catch(function(err) {
        showToast('Ошибка соединения: ' + err.message, 'error');
        if (btn) { resetBtn(btn); }
      });
  }

  function pollRunStatus(runId, btn) {
    if (pollingIntervals[runId]) clearInterval(pollingIntervals[runId]);
    var attempts = 0;

    function check() {
      fetch('/web/sync-center/runs/' + runId + '/status')
        .then(function(r) { return r.json(); })
        .then(function(data) {
          if (data.status === 'success') {
            showToast(data.message || 'Синхронизация завершена успешно', 'success');
            if (btn) {
              btn.textContent = '✓ Успешно';
              btn.classList.remove('running');
              btn.classList.add('success-flash');
              setTimeout(function() { resetBtn(btn); }, 3000);
            }
            clearInterval(pollingIntervals[runId]);
            delete pollingIntervals[runId];
          } else if (data.status === 'warning') {
            showToast(data.message || 'Синхронизация завершена с предупреждениями', 'warn');
            if (btn) {
              btn.textContent = '⚠ Предупреждение';
              btn.classList.remove('running');
              btn.classList.add('error-flash');
              setTimeout(function() { resetBtn(btn); }, 5000);
            }
            clearInterval(pollingIntervals[runId]);
            delete pollingIntervals[runId];
          } else if (data.status === 'error' || data.status === 'timeout') {
            var msg = data.status === 'timeout' ? 'Превышено время выполнения' : (data.message || 'Ошибка синхронизации');
            showToast(msg, 'error');
            if (btn) {
              btn.textContent = data.status === 'timeout' ? '⏱ Таймаут' : '✗ Ошибка';
              btn.classList.remove('running');
              btn.classList.add('error-flash');
              setTimeout(function() { resetBtn(btn); }, 4000);
            }
            clearInterval(pollingIntervals[runId]);
            delete pollingIntervals[runId];
          } else if (data.status === 'running' || data.status === 'queued') {
            attempts++;
            if (btn && btn.textContent !== 'Выполняется...') {
              btn.textContent = 'Выполняется...';
            }
          }
        })
        .catch(function() {
          attempts++;
          if (attempts > 30) {
            clearInterval(pollingIntervals[runId]);
            delete pollingIntervals[runId];
            if (btn) { resetBtn(btn); }
          }
        });
    }

    pollingIntervals[runId] = setInterval(check, 2000);
    setTimeout(function() {
      if (pollingIntervals[runId]) {
        clearInterval(pollingIntervals[runId]);
        delete pollingIntervals[runId];
        if (btn) { resetBtn(btn); }
      }
    }, 120000);
  }

  function resetBtn(btn) {
    if (!btn || !(btn instanceof HTMLElement)) return;
    btn.disabled = false;
    btn.classList.remove('running', 'success-flash', 'error-flash');
    var syncType = btn.getAttribute('data-sync-type');
    var labels = {
      'all': '↻ Синхронизировать всё',
      'products': '📦 Товары',
      'stocks': '📊 Остатки',
      'orders': '📋 Сборочные задания FBS',
      'wb_orders_stats': '📋 Заказы WB',
      'wb_fbs_assembly_orders': '📋 Сборочные задания FBS',
      'sales': '💰 Продажи',
      'returns': '↩ Возвраты',
      'profile': '👤 Профиль',
      'finances': '💳 Финансы',
      'reports': '📑 Отчёты WB',
      'logistics': '🚚 Логистика WB',
      'wb_financial_details': '📊 Финансовые детализации WB',
      'ozon_finances': '💳 Финансы Ozon',
      'ozon_balance': '⚖ Баланс Ozon',
      'wb_reports': '📑 Отчёты WB',
      'wb_promotions': '🏷 Акции WB',
    };
    btn.textContent = labels[syncType] || 'Запустить';
  }

  function verifyApiKey(accountId, btn) {
    if (btn && btn.disabled) return;
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Проверка...';
    }

    fetch('/web/sync-center/accounts/' + accountId + '/verify-api-key', { method: 'POST' })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.ok && data.status === 'valid') {
          showToast('API-ключ действителен', 'success');
          if (btn) { btn.textContent = '✓ Ключ OK'; }
        } else {
          showToast(data.message || 'API-ключ недействителен', 'error');
          if (btn) { btn.textContent = '✗ Ошибка ключа'; }
        }
        if (btn) {
          setTimeout(function() {
            btn.disabled = false;
            btn.textContent = '🔑 Проверить API-ключ';
          }, 5000);
        }
        setTimeout(function() { location.reload(); }, 2000);
      })
      .catch(function(err) {
        showToast('Ошибка проверки: ' + err.message, 'error');
        if (btn) {
          btn.disabled = false;
          btn.textContent = '🔑 Проверить API-ключ';
        }
      });
  }

  document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('[data-sync-type]').forEach(function(btn) {
      btn.addEventListener('click', function(e) {
        var accountId = btn.getAttribute('data-account-id');
        var syncType = btn.getAttribute('data-sync-type');
        var marketplace = btn.getAttribute('data-marketplace');
        triggerSync(accountId, syncType, marketplace, btn);
      });
    });

    document.querySelectorAll('[data-verify-key]').forEach(function(btn) {
      btn.addEventListener('click', function(e) {
        var accountId = btn.getAttribute('data-account-id');
        verifyApiKey(accountId, btn);
      });
    });

    document.querySelectorAll('[data-preset]').forEach(function(btn) {
      btn.addEventListener('click', function(e) {
        var preset = btn.getAttribute('data-preset');
        selectSyncPeriodPreset(preset);
      });
    });
  });

  window.retryAllStale = function() {
    if (!confirm('Запустить синхронизацию для всех просроченных типов данных?')) return;
    document.querySelectorAll('[data-sync-type]').forEach(function(btn) {
      if (!btn.disabled && !btn.classList.contains('running')) {
        var accountId = btn.getAttribute('data-account-id');
        var syncType = btn.getAttribute('data-sync-type');
        var marketplace = btn.getAttribute('data-marketplace');
        if (syncType !== 'all') {
          triggerSync(accountId, syncType, marketplace, btn);
        }
      }
    });
    showToast('Запуск синхронизаций...', 'info');
  };

  window.retryAllErrors = function() {
    if (!confirm('Запустить повтор всех ошибочных синхронизаций?')) return;
    document.querySelectorAll('.attention-item.bad [data-sync-type]').forEach(function(btn) {
      var accountId = btn.getAttribute('data-account-id');
      var syncType = btn.getAttribute('data-sync-type');
      var marketplace = btn.getAttribute('data-marketplace');
      triggerSync(accountId, syncType, marketplace, btn);
    });
    showToast('Повтор проблемных синхронизаций...', 'info');
  };
})();
"""
