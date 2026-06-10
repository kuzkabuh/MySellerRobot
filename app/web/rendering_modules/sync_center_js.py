"""JavaScript for Sync Center: auto-refresh, run sync, verify API key, toasts."""

SYNC_CENTER_JS = """
(function() {
  var pollingIntervals = {};

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

  function getCookie(name) {
    var match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
    return match ? decodeURIComponent(match[2]) : null;
  }

  function triggerSync(accountId, syncType, marketplace, btn) {
    if (btn && (btn.disabled || btn.classList.contains('running'))) return;

    if (syncType === 'all') {
      if (!confirm('Запустить синхронизацию всех типов данных для этого кабинета?')) return;
      var syncTypes = ['products', 'stocks', 'orders', 'sales', 'returns', 'profile', 'finances'];
      if (marketplace === 'WB') {
        syncTypes.push('wb_reports', 'logistics', 'wb_financial_details');
      } else {
        syncTypes.push('ozon_finances');
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

    fetch(url, { method: 'POST', headers: { 'x-forwarded-for': window.location.host } })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.ok) {
          showToast(data.message || 'Синхронизация запущена', 'success');
          if (data.run_id) {
            pollRunStatus(data.run_id, btn);
          } else if (btn) {
            btn.textContent = 'Запущен';
            setTimeout(function() { resetBtn(btn); }, 3000);
          }
        } else {
          showToast(data.message || 'Ошибка запуска', 'error');
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
      'orders': '📋 Заказы',
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
